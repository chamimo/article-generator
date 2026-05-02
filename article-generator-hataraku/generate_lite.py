"""
軽量版記事生成システム (Phase 1)

既存システム（main.py）とは独立した新規実装。
既存ファイルは一切変更しない。

Usage:
    python generate_lite.py
    python generate_lite.py --dry-run
    python generate_lite.py --keyword "ChatGPT 使い方" --volume 8100

Phase 1（現在）:
    候補シートから複数キーワード選定 → 記事生成（ARTICLE_COUNT件）→ WP下書き保存

Phase 2（予定）:
    - 記事タイプ別生成（トレンド / ロングテール / 収益化）
    - Xからトレンドキーワード取得
    - 投稿済み重複チェック
    - 複数ブログ対応
    - アイキャッチ画像生成
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

# ── --site を config import 前に解決 ─────────────────────────────────────
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--site", default="workup-ai")
_pre_args, _ = _pre.parse_known_args()
os.environ["ARTICLE_SITE"] = _pre_args.site

# ── 既存モジュールをそのまま流用（変更なし）────────────────────────────
from config import (
    ANTHROPIC_API_KEY,
    GOOGLE_CREDENTIALS_PATH,
    WP_URL,
    WP_USERNAME,
    WP_APP_PASSWORD,
)
from modules.article_generator import generate_article
from modules.wordpress_poster import create_post, post_article_with_image
from modules.image_generator import generate_image_for_article
from modules.api_guard import check_stop, daily_summary
from modules import wp_context
from modules.wp_pattern_fetcher import fetch_patterns, match_pattern, insert_pattern_cta

# ブログ別マイパターンキャッシュ（セッション中の再フェッチを防ぐ）
_wp_patterns_cache: dict[str, list] = {}


def _remove_dead_external_links(content: str) -> str:
    """
    記事HTML内の外部リンクを検証し、存在しないURL（404・接続不可）の
    <a>タグを除去してリンクテキストだけ残す。

    - 内部リンク（WP自サイト）はスキップ
    - HEADリクエストで確認（タイムアウト5秒）
    - 並列チェックで速度を確保（最大8スレッド）
    """
    import re
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import urllib.request

    # 外部リンクを全件抽出
    pattern = re.compile(
        r'<a\s[^>]*href=["\'](?P<url>https?://[^"\']+)["\'][^>]*>(?P<text>.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    matches = list(pattern.finditer(content))
    if not matches:
        return content

    # WPサイト自身のURLは除外（内部リンク）
    try:
        from modules import wp_context
        own_host = wp_context.get_wp_url().rstrip("/").replace("https://", "").replace("http://", "")
    except Exception:
        own_host = ""

    def check_url(url: str) -> tuple[str, bool]:
        """(url, is_alive) を返す。alive=True なら残す。"""
        if own_host and own_host in url:
            return url, True  # 内部リンクは常にOK

        import urllib.parse
        # 日本語等の非ASCII文字をパーセントエンコード
        parsed = urllib.parse.urlsplit(url)
        encoded_path = urllib.parse.quote(parsed.path, safe="/-_.~!$&'()*+,;=:@")
        encoded_url  = urllib.parse.urlunsplit(parsed._replace(path=encoded_path))

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ja,en;q=0.9",
        }

        # HEAD → GET の順で試す（HEADを拒否するサーバー対応）
        for method in ("HEAD", "GET"):
            try:
                req = urllib.request.Request(encoded_url, method=method, headers=headers)
                with urllib.request.urlopen(req, timeout=6) as res:
                    return url, res.status < 400
            except urllib.error.HTTPError as e:
                if e.code == 405 and method == "HEAD":
                    continue  # HEAD不可 → GETで再試行
                return url, e.code < 400
            except Exception:
                if method == "HEAD":
                    continue  # ネットワーク系エラーもGETで再試行
                return url, False

        return url, False

    # 並列チェック
    urls = list({m.group("url") for m in matches})
    url_alive: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(check_url, u): u for u in urls}
        for f in as_completed(futures):
            url, alive = f.result()
            url_alive[url] = alive

    # 死リンクをリンクテキストに置換（後ろから処理してインデックスずれを防ぐ）
    dead_urls = [u for u, ok in url_alive.items() if not ok]
    if not dead_urls:
        return content

    removed = 0
    for m in reversed(matches):
        if m.group("url") in dead_urls:
            content = content[:m.start()] + m.group("text") + content[m.end():]
            removed += 1

    if removed:
        log.info(f"[link_check] 死リンク除去: {removed}件 / チェック: {len(urls)}件")
        for u in dead_urls:
            log.debug(f"[link_check]   削除: {u}")

    return content


def _insert_rakuten_shortcode(content: str) -> str:
    """
    楽天トラベルショートコードを2箇所に挿入する（hida-no-omoide 専用）。

    挿入位置:
      A) まとめH2直前
         ← リード文「泊まるともっと楽しめる」導線 + ショートコード
      B) 記事末尾
         ← 軽い締め一言 + ショートコード

    まとめH2が見つからない場合は、後半最初のH2直前(A) と末尾(B) に挿入する。
    """
    import re

    SC = '\n<!-- wp:shortcode -->\n[rakuten_hida_hotels]\n<!-- /wp:shortcode -->\n'

    # ---- リード文（まとめ直前） ----
    LEAD = (
        '\n<!-- wp:paragraph -->\n'
        '<p>飛騨の旅をもっと深く味わいたいなら、ぜひ一泊してみてください。'
        '朝靄に包まれた古い町並みや、静まり返った夜の宿場の空気は、'
        '日帰りでは決して出会えない時間です。'
        '以下に、エリア内でおすすめのホテル・旅館をまとめました。</p>\n'
        '<!-- /wp:paragraph -->\n'
    )

    # ---- 末尾の締め一言 ----
    CLOSING = (
        '\n<!-- wp:paragraph -->\n'
        '<p>宿選びに迷ったら、楽天トラベルで口コミと料金を比べてみてください。'
        'お気に入りの一軒に出会えれば、飛騨の思い出がさらに色鮮やかになるはずです。</p>\n'
        '<!-- /wp:paragraph -->\n'
    )

    # ---- まとめH2/H3を探す ----
    _MATOME_PAT = re.compile(
        r'<!-- wp:heading[^>]*-->'
        r'\s*<h[23][^>]*>[^<]*(?:まとめ|総まとめ)[^<]*</h[23]>'
        r'\s*<!-- /wp:heading -->',
        re.DOTALL,
    )
    matome_m = _MATOME_PAT.search(content)

    # ---- 後半最初のH2を探す（まとめ未検出時のフォールバック） ----
    _H2_PAT = re.compile(
        r'<!-- wp:heading[^>]*-->\s*<h2[^>]*>',
        re.DOTALL,
    )
    h2_positions = [m.start() for m in _H2_PAT.finditer(content)]

    # ---- 挿入位置A をオリジナルのコンテンツで計算 ----
    if matome_m:
        pos_a = matome_m.start()
    elif len(h2_positions) >= 2:
        # まとめがない場合: 後半最初のH2（全H2の後半1/2の先頭）を目安にする
        midpoint = len(h2_positions) // 2
        pos_a = h2_positions[midpoint]
    else:
        # H2が1本以下: 全段落の後半先頭付近
        paras = list(re.finditer(r'<!-- /wp:paragraph -->', content))
        mid_idx = max(0, len(paras) * 2 // 3 - 1)
        pos_a = paras[mid_idx].end() if paras else len(content) // 2

    pos_b = len(content)  # 末尾

    # ---- 後ろ→前の順で挿入（インデックスずれを防ぐ） ----
    # B: 末尾に追記
    content = content + CLOSING + SC

    # A: まとめ直前（位置はオリジナル基準なので pos_a はまだ有効）
    content = content[:pos_a] + LEAD + SC + content[pos_a:]

    return content


def _insert_hotel_pattern(content: str) -> str:
    """
    再利用ブロック「ホテル紹介」(ID=144) を FAQ直前に挿入する（hida-no-omoide 全記事）。

    挿入位置の優先順:
      1. <!-- wp:loos/faq --> の直前
      2. まとめH2/H3 の直前
      3. 末尾
    """
    import re

    BLOCK = '\n<!-- wp:block {"ref":144} /-->\n'

    # 1. FAQ ブロックを探す
    faq_m = re.search(r'<!-- wp:loos/faq[ >]', content)
    if faq_m:
        pos = faq_m.start()
        return content[:pos] + BLOCK + content[pos:]

    # 2. まとめH2/H3 を探す
    matome_m = re.search(
        r'<!-- wp:heading[^>]*-->\s*<h[23][^>]*>[^<]*(?:まとめ|総まとめ)[^<]*</h[23]>',
        content, re.DOTALL
    )
    if matome_m:
        pos = matome_m.start()
        return content[:pos] + BLOCK + content[pos:]

    # 3. 末尾
    return content + BLOCK


# ═══════════════════════════════════════════════════════════════
# FEATURE FLAGS
# Phase 2以降で True に切り替える。既存ロジックには影響しない。
# ═══════════════════════════════════════════════════════════════
FEATURES: dict[str, bool] = {
    "trend_from_x":     False,  # (未使用) X API連携 → fetch_trend_keywords() に置換
    "trend_auto_fetch": False,  # キーワードシート外からのトレンドKW自動取得（無効=シートのみ使用）
    "article_type_mix": True,   # Phase 2: 記事タイプ配分制御（longtail/trend/monetize）
    "duplicate_check":  True,   # Phase 2: 投稿済み重複チェック
    "image_generation": True,   # Phase 2: アイキャッチ画像生成
    "multi_blog":       True,   # Phase 2: 複数ブログ対応
    "sheets_update":    False,  # Phase 2: 投稿済みフラグをシートに書き込む
}

# ═══════════════════════════════════════════════════════════════
# CONFIG
# Phase 2でブログ別 config.py に移動予定
# ═══════════════════════════════════════════════════════════════
CANDIDATE_SS_ID   = "1_pgNf2-JNlT2uwJFGzlVPGpuVpj2mf5eSsa_YLwMwGc"
CANDIDATE_SHEET   = "絞り込みKW"
ARTICLE_COUNT     = 3      # 1回の実行で生成する記事数
MIN_VOLUME        = 100    # 最低月間検索数（これ未満は選定対象外）
TOP_N_CANDIDATES  = 50     # 上位N件から選定（ランダム性のための幅）
INTER_ARTICLE_WAIT = 3     # 記事間のウェイト秒数（API負荷対策）
OUTPUT_LOG_DIR    = Path(__file__).parent / "output"
WP_RECENT_DAYS    = 7      # 直近N日以内の記事を重複候補として扱う
TITLE_SIM_THRESHOLD      = 0.75  # タイトル類似度閾値（キーワード→タイトル比較、Jaccard bigram）
POST_GEN_SIM_THRESHOLD   = 0.40  # 生成後タイトル重複判定閾値（タイトル→タイトル比較）
BLOGS_DIR         = Path(__file__).parent / "blogs"

# Phase 2: 記事タイプ配分（article_type_mix=True 時に使用）
ARTICLE_TYPE_WEIGHTS: dict[str, float] = {
    "longtail": 0.5,   # ロングテール記事（安定流入）
    "trend":    0.3,   # トレンド記事（短期流入）
    "monetize": 0.2,   # 収益化記事（CV重視）
}

# 全ブログ共通NGワード（部分一致でスキップ）
GLOBAL_NG_KEYWORDS: list[str] = [
    "怪しい", "詐欺", "返金", "被害", "トラブル", "やばい",
]


# ═══════════════════════════════════════════════════════════════
# ARTICLE TYPE
# Phase 2で記事生成ロジックの分岐に使用
# ═══════════════════════════════════════════════════════════════
class ArticleType(Enum):
    LONGTAIL = "longtail"   # ロングテール：SEO安定流入狙い
    TREND    = "trend"      # トレンド：時事・季節性キーワード（Phase 2）
    MONETIZE = "monetize"   # 収益化：CVR高いキーワード（Phase 2）


class DuplicateSkipError(Exception):
    """タイトル重複によるスキップを示す例外。エラーとはカウントしない。"""
    pass


# ═══════════════════════════════════════════════════════════════
# BLOG CONFIG
# ブログごとの設定を保持する dataclass。
# blogs/<name>/blog_config.json から読み込む。
# ═══════════════════════════════════════════════════════════════
@dataclass
class BlogConfig:
    name:             str
    display_name:     str
    genre:            str
    target_length:    int | dict  # int（全タイプ共通）or {"MONETIZE":9000,"LONGTAIL":6000,...}
    fact_check:       bool
    candidate_ss_id:  str
    candidate_sheet:  str
    article_count:    int
    min_volume:       int
    wp_url:           str
    wp_username:      str
    wp_app_password:  str
    article_type_weights: dict = field(default_factory=lambda: dict(ARTICLE_TYPE_WEIGHTS))
    stop_words: list = field(default_factory=list)  # コアKW正規化用除外ワード
    aliases: list = field(default_factory=list)         # --blog で使える別名リスト
    allowed_themes: list = field(default_factory=list)  # テーマホワイトリスト（空=無制限）
    ng_keywords: list = field(default_factory=list)     # NGワードブラックリスト
    asp_links: dict = field(default_factory=dict)       # ASP案件リンク {名称: URL}（静的フォールバック）
    affili_ss_id: str = ""                              # アフィリURLシートのスプレッドシートID（空=シート読み込みなし）
    guide_links: dict = field(default_factory=dict)    # 内部誘導リンク {pv_url, comparison_url, cv_url}
    wp_post_status: str = "draft"                      # 投稿方式: "draft"（下書き）or "publish"（即公開）
    image_style: dict = field(default_factory=dict)    # 画像生成スタイル設定
    asp_ss_id:   str  = ""                             # ASP専用SS（空=candidate_ss_idを使用）
    # ブログ管理シートから動的取得（空 = Claude自動判断）
    site_purpose:  str = ""  # サイトの目的
    target:        str = ""  # ターゲット読者
    writing_taste: str = ""  # 文章のテイスト
    genre_detail:  str = ""  # ジャンル詳細
    search_intent: str = ""  # 検索意図タイプ（Know / Do / Buy）
    # 追加設定はここに列追加するだけで OK
    extra: dict = field(default_factory=dict)


def _normalize_asp_links(raw: dict) -> dict[str, str]:
    """
    asp_links の値として文字列（URL）または
    {"url": "...", "aliases": ["別表記1", "別表記2"]} 両方に対応する。

    返り値はフラットな {表記: URL} 辞書。
    エイリアスも同じ URL に展開されるため、
    internal_linker 側は変更不要。

    Example:
        {"クラウドワークス": {"url": "https://...", "aliases": ["CrowdWorks", "クラウドワーク"]}}
        → {"クラウドワークス": "https://...", "CrowdWorks": "https://...", "クラウドワーク": "https://..."}
    """
    result: dict[str, str] = {}
    for name, val in raw.items():
        if isinstance(val, str):
            result[str(name)] = val
        elif isinstance(val, dict):
            url = str(val.get("url", ""))
            result[str(name)] = url
            for alias in val.get("aliases", []):
                result[str(alias)] = url
    return result


def load_blog_config(blog_name: str) -> BlogConfig:
    """
    blogs/<blog_name>/blog_config.json を読み込んで BlogConfig を返す。

    WP 認証情報は json の <key>_env フィールドで env var 名を指定し、
    環境変数から取得する（config.py の既存変数をデフォルト値として使用）。
    """
    config_path = BLOGS_DIR / blog_name / "blog_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"blog_config.json が見つかりません: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)

    def resolve(key: str, env_key: str, fallback: str) -> str:
        """設定値を直書き → env var 名経由 → フォールバック の順で解決する。"""
        if data.get(key):
            return data[key]
        env_name = data.get(f"{key}_env", env_key)
        return os.environ.get(env_name, fallback)

    cfg = BlogConfig(
        name            = blog_name,
        display_name    = data.get("display_name", blog_name),
        genre           = data.get("genre", ""),
        target_length   = (data["target_length"] if isinstance(data.get("target_length"), dict)
                           else int(data.get("target_length", 9000))),
        fact_check      = bool(data.get("fact_check", True)),
        candidate_ss_id = (data.get("candidate_ss_id")
                           or os.environ.get(data.get("candidate_ss_id_env", ""), "")
                           or CANDIDATE_SS_ID),
        candidate_sheet = data.get("candidate_sheet", CANDIDATE_SHEET),
        article_count   = int(data.get("article_count", ARTICLE_COUNT)),
        min_volume      = int(data.get("min_volume", MIN_VOLUME)),
        wp_url          = resolve("wp_url", "WP_URL", WP_URL),
        wp_username     = resolve("wp_username", "WP_USERNAME", WP_USERNAME),
        wp_app_password = resolve("wp_app_password", "WP_APP_PASSWORD", WP_APP_PASSWORD),
        article_type_weights = data.get("article_type_weights", ARTICLE_TYPE_WEIGHTS),
        stop_words      = [str(w) for w in data.get("stop_words", [])],
        aliases         = [str(a) for a in data.get("aliases", [])],
        allowed_themes  = [str(t) for t in data.get("allowed_themes", [])],
        ng_keywords     = [str(k) for k in data.get("ng_keywords", [])],
        asp_links       = _normalize_asp_links(data.get("asp_links", {})),
        affili_ss_id    = data.get("affili_ss_id", ""),
        guide_links     = data.get("guide_links", {}),
        wp_post_status  = data.get("wp_post_status", "draft"),
        image_style     = data.get("image_style", {}),
        asp_ss_id       = data.get("asp_ss_id", ""),
        extra           = {k: v for k, v in data.items()
                           if k not in ("name", "display_name", "genre", "target_length",
                                        "fact_check", "candidate_ss_id", "candidate_sheet",
                                        "article_count", "min_volume", "wp_url", "wp_username",
                                        "wp_app_password", "article_type_weights",
                                        "stop_words", "aliases", "allowed_themes",
                                        "ng_keywords", "asp_links", "affili_ss_id",
                                        "guide_links", "wp_post_status",
                                        "image_style", "asp_ss_id", "_comment")
                           and not k.endswith("_env")},
    )
    # ブログ管理シートから追加メタデータを補完
    try:
        from modules.blog_meta import load_blog_meta
        meta = load_blog_meta(blog_name, credentials_path=GOOGLE_CREDENTIALS_PATH)
        if meta.get("site_purpose"):  cfg.site_purpose  = meta["site_purpose"]
        if meta.get("target"):         cfg.target        = meta["target"]
        if meta.get("writing_taste"):  cfg.writing_taste = meta["writing_taste"]
        if meta.get("genre"):          cfg.genre_detail  = meta["genre"]
        if meta.get("search_intent"):  cfg.search_intent = meta["search_intent"]
    except Exception:
        pass
    return cfg


def list_blogs() -> list[str]:
    """blogs/ ディレクトリ以下に blog_config.json を持つブログ名を返す。"""
    if not BLOGS_DIR.exists():
        return []
    return sorted(
        d.name for d in BLOGS_DIR.iterdir()
        if d.is_dir() and (d / "blog_config.json").exists()
    )


def resolve_blog(identifier: str) -> str:
    """
    番号または名前（大文字小文字不問）からブログのディレクトリ名を解決する。

    解決順:
      1. 番号（"1", "2", ...）→ list_blogs() のソート順でインデックス対応
      2. ディレクトリ名と大文字小文字無視で一致
      3. blog_config.json の aliases フィールドと一致

    見つからない場合はブログ一覧を表示して sys.exit(1)。
    """
    blogs = list_blogs()
    ident_lower = identifier.strip().lower()

    # 番号指定
    if ident_lower.isdigit():
        idx = int(ident_lower) - 1
        if 0 <= idx < len(blogs):
            return blogs[idx]
        print(f"エラー: ブログ番号 {identifier} は存在しません。\n")
        _print_blog_list(blogs)
        sys.exit(1)

    # 名前 / エイリアス指定（大文字小文字不問）
    for blog_name in blogs:
        if blog_name.lower() == ident_lower:
            return blog_name
        # aliases を確認
        try:
            cfg_path = BLOGS_DIR / blog_name / "blog_config.json"
            with open(cfg_path, encoding="utf-8") as f:
                data = json.load(f)
            aliases = [str(a).lower() for a in data.get("aliases", [])]
            if ident_lower in aliases:
                return blog_name
        except Exception:
            pass

    print(f"エラー: ブログ「{identifier}」が見つかりません。\n")
    _print_blog_list(blogs)
    sys.exit(1)


def _print_blog_list(blogs: list[str]) -> None:
    """ブログ一覧を番号付きで表示する。"""
    print("利用可能なブログ一覧:")
    for i, name in enumerate(blogs, 1):
        try:
            cfg_path = BLOGS_DIR / name / "blog_config.json"
            with open(cfg_path, encoding="utf-8") as f:
                data = json.load(f)
            display = data.get("display_name", name)
            aliases = data.get("aliases", [])
            alias_str = f"  ({', '.join(aliases)})" if aliases else ""
            wp_url = data.get("wp_url", "")
            if not wp_url:
                env_key = data.get("wp_url_env", "WP_URL")
                wp_url = os.environ.get(env_key, "未設定")
            domain = wp_url.replace("https://", "").replace("http://", "").rstrip("/")
            print(f"  {i}: {name}  [{display} / {domain}]{alias_str}")
        except Exception:
            print(f"  {i}: {name}")


def confirm_blog(blog_cfg: "BlogConfig", skip: bool = False) -> bool:
    """
    実行前の確認プロンプトを表示し、y なら True を返す。

    skip=True または stdin が TTY でない場合（cron等）は確認なしで True を返す。
    """
    if skip or not sys.stdin.isatty():
        return True
    domain = blog_cfg.wp_url.replace("https://", "").replace("http://", "").rstrip("/")
    print(f"\n{blog_cfg.display_name}（{domain}）を処理します。よろしいですか？ [y/n]: ", end="", flush=True)
    answer = input().strip().lower()
    return answer == "y"


# ═══════════════════════════════════════════════════════════════
# LOGGER
# ═══════════════════════════════════════════════════════════════
def _setup_logger(name: str = "generate_lite") -> logging.Logger:
    """コンソール + ファイルの両方に出力するロガーをセットアップ。"""
    OUTPUT_LOG_DIR.mkdir(exist_ok=True)
    log_file = OUTPUT_LOG_DIR / f"lite_{datetime.now().strftime('%Y%m%d')}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger  # 再設定防止

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # コンソール
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # ファイル（DEBUG以上）
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


log = _setup_logger()


def _log_result(result: dict) -> None:
    """処理結果を JSON でログファイルに保記録する（後で集計しやすくするため）。"""
    OUTPUT_LOG_DIR.mkdir(exist_ok=True)
    result_file = OUTPUT_LOG_DIR / f"lite_results_{datetime.now().strftime('%Y%m')}.jsonl"
    with open(result_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════════════════════════
# STEP 1: 候補シート読み込み
# Phase 2: article_type に応じて Xトレンド or シートを切り替え予定
# ═══════════════════════════════════════════════════════════════
def fetch_candidates(
    article_type: ArticleType = ArticleType.LONGTAIL,
    blog_cfg: BlogConfig | None = None,
) -> list[dict]:
    """
    候補シートからキーワードを読み込む。

    blog_cfg が指定された場合はそのブログの設定（ss_id / sheet / min_volume）を使用する。
    Phase 2で article_type == TREND の場合は X API から取得する予定。

    Returns:
        [{"keyword": str, "volume": int, "seo_difficulty": int|None, "competition": int|None}, ...]
    """
    # Phase 2: トレンド記事はXから取得
    if FEATURES["trend_from_x"] and article_type == ArticleType.TREND:
        raise NotImplementedError("Xトレンド取得はPhase 2で実装予定")

    ss_id  = blog_cfg.candidate_ss_id  if blog_cfg else CANDIDATE_SS_ID
    sheet  = blog_cfg.candidate_sheet  if blog_cfg else CANDIDATE_SHEET
    min_vol = blog_cfg.min_volume      if blog_cfg else MIN_VOLUME

    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc    = gspread.authorize(creds)
    ws    = gc.open_by_key(ss_id).worksheet(sheet)

    rows   = ws.get_all_values()
    header = rows[0] if rows else []
    log.debug(f"[fetch] シート「{CANDIDATE_SHEET}」: {len(rows)-1}行 / ヘッダー: {header}")

    # 列インデックス検出（列名が変わっても動くように）
    def col(names: list[str]) -> int:
        for name in names:
            if name in header:
                return header.index(name)
        return -1

    kw_idx        = col(["キーワード", "Keyword"])
    vol_idx       = col(["月間検索数", "検索ボリューム", "volume"])
    seo_idx       = col(["SEO難易度", "seo_difficulty"])
    comp_idx      = col(["競合性", "competition"])
    aim_idx       = col(["aim", "AIM", "Aim"])
    status_idx    = col(["投稿ステータス", "ステータス", "status"])  # 投稿済み除外用
    hantei_idx    = col(["判定"])       # D列: 親KW / サブKW （新フォーマット）
    togo_saki_idx = col(["統合先KW"])   # E列: 統合先KW （新フォーマット）
    is_new_format = hantei_idx >= 0    # 判定列の有無で新旧フォーマットを判別

    # aim列の値 → 優先度レベル（高いほど先に評価）
    _AIM_PRIORITY = {"now": 4, "future": 3, "monetize": 2, "aim": 1, "claude": 1, "add": 1}

    def to_int(v: str) -> int | None:
        if not v or v.upper() in ("N/A", "NULL", "-", ""):
            return None
        try:
            return int(float(v))
        except ValueError:
            return None

    MAIN_VOL_THRESHOLD = 30  # これ以上（またはN/A）→ 記事生成対象

    candidates: list[dict] = []   # メインKW（vol>=30 or N/A）
    sub_keywords: list[str] = []  # サブKW（vol<30）→ 記事本文に盛り込む
    n_posted_skip = 0             # 投稿済みスキップ件数（ログ用）
    sub_kws_map: dict[str, list[str]] = {}  # 親KW → サブKWリスト（新フォーマット専用）
    n_sub_kw_skip = 0             # サブKW除外件数（新フォーマット）

    for row in rows[1:]:
        def cell(i: int) -> str:
            return row[i].strip() if 0 <= i < len(row) else ""

        kw   = cell(kw_idx)
        vol_raw = cell(vol_idx)
        vol  = to_int(vol_raw)      # None = N/A
        seo  = to_int(cell(seo_idx))
        comp = to_int(cell(comp_idx))
        aim  = cell(aim_idx).lower().strip() if aim_idx >= 0 else ""
        post_status  = cell(status_idx).strip()    if status_idx    >= 0 else ""
        hantei       = cell(hantei_idx).strip()    if hantei_idx    >= 0 else ""
        togo_saki    = cell(togo_saki_idx).strip() if togo_saki_idx >= 0 else ""

        if not kw:
            continue

        # ── 新フォーマット（判定列あり）専用処理 ──────────────────────
        if is_new_format:
            # AIM列が "aim" / "claude"（Claude Code追加分）/ "add"（ユーザー追加）の行のみ対象
            if aim not in ("aim", "claude", "add"):
                continue
            # サブKW行：記事生成しない → 統合先KWに紐付けて蓄積
            if hantei == "サブKW":
                if togo_saki:
                    sub_kws_map.setdefault(togo_saki, []).append(kw)
                n_sub_kw_skip += 1
                continue
            # 要確認・統合対象はスキップ（人間の確認待ち or かにばり統合済み）
            if hantei == "要確認" or post_status in ("統合対象",):
                n_posted_skip += 1
                continue

        # 投稿済みキーワードはスキップ（新旧共通）
        if post_status in ("投稿済み", "カニバリスキップ"):
            n_posted_skip += 1
            continue

        # vol=N/A（None）はメイン扱い、明示的な数値は30以上のみメイン
        is_main = (vol is None) or (vol >= MAIN_VOL_THRESHOLD)
        vol_int = vol if vol is not None else 0

        if not is_main:
            # vol<30 → サブKWとして収集（旧フォーマット用）
            sub_keywords.append(kw)
            continue

        if vol_int < min_vol:
            continue

        candidates.append({
            "keyword":         kw,
            "volume":          vol_int,
            "seo_difficulty":  seo,
            "competition":     comp,
            "priority":        aim == "now",
            "_aim":            aim,
            "_priority_level": _AIM_PRIORITY.get(aim, 0),
        })

    # 新フォーマット: 各候補にサブKWを直接紐付け
    if is_new_format:
        for c in candidates:
            c["_sub_kws"] = sub_kws_map.get(c["keyword"], [])
        if sub_kws_map:
            log.info(f"[fetch] サブKW紐付け: {sum(len(v) for v in sub_kws_map.values())}件 → {len([c for c in candidates if c.get('_sub_kws')])}記事に統合")

    # aim優先度の内訳をログに出す
    aim_counts: dict[str, int] = {}
    for c in candidates:
        lv = c.get("_aim") or "—"
        aim_counts[lv] = aim_counts.get(lv, 0) + 1
    aim_summary = ", ".join(
        f"{k}:{v}" for k, v in sorted(aim_counts.items(),
            key=lambda kv: -_AIM_PRIORITY.get(kv[0], 0))
        if k != "—"
    )
    # ── テーマフィルタ（ホワイトリスト + ブラックリスト）──────────
    allowed_themes = blog_cfg.allowed_themes if blog_cfg else []
    ng_keywords    = blog_cfg.ng_keywords    if blog_cfg else []

    def _passes_theme(kw: str) -> bool:
        kw_l = kw.lower()
        # 全ブログ共通NGワードチェック（部分一致）
        if any(ng in kw_l for ng in GLOBAL_NG_KEYWORDS):
            return False
        # ブログ固有NGワードチェック（ブラックリスト）
        if ng_keywords and any(ng.lower() in kw_l for ng in ng_keywords):
            return False
        # テーマチェック（ホワイトリスト）
        if not allowed_themes:
            return True  # リストなし = 全件OK
        return any(theme.lower() in kw_l for theme in allowed_themes)

    before_filter = len(candidates)
    candidates  = [c for c in candidates  if _passes_theme(c["keyword"])]
    sub_keywords = [k for k in sub_keywords if _passes_theme(k)]
    filtered_out = before_filter - len(candidates)

    log.info(
        f"[fetch] [{sheet}] メインKW: {len(candidates)}件（vol≥{MAIN_VOL_THRESHOLD} or N/A）"
        + (f"  サブKW除外: {n_sub_kw_skip}件（統合対象）" if n_sub_kw_skip else
           f"  サブKW: {len(sub_keywords)}件（vol<{MAIN_VOL_THRESHOLD}）")
        + (f"  投稿済みスキップ: {n_posted_skip}件" if n_posted_skip else "")
        + (f"  テーマ外除外: {filtered_out}件" if filtered_out else "")
        + (f"  aim内訳: [{aim_summary}]" if aim_summary else "")
    )
    return candidates, sub_keywords


# ═══════════════════════════════════════════════════════════════
# STEP 1.5: WP公開記事取得 & 重複チェック
# ═══════════════════════════════════════════════════════════════
def fetch_wp_posts(blog_cfg: BlogConfig | None = None) -> list[dict]:
    """
    WordPress REST API で公開・下書き・非公開記事を全件取得する。
    ゴミ箱のみ除外。blog_cfg が指定された場合はそのブログの WP 認証情報を使用する。

    Returns:
        [{"id": int, "title": str, "slug": str, "date": str, "status": str}, ...]
    """
    import requests
    from requests.auth import HTTPBasicAuth

    wp_url      = blog_cfg.wp_url          if blog_cfg else WP_URL
    wp_user     = blog_cfg.wp_username     if blog_cfg else WP_USERNAME
    wp_password = blog_cfg.wp_app_password if blog_cfg else WP_APP_PASSWORD

    auth     = HTTPBasicAuth(wp_user, wp_password)
    base     = wp_url.rstrip("/")
    endpoint = f"{base}/wp-json/wp/v2/posts"
    params: dict = {
        "status":   "publish,draft,private",  # ゴミ箱以外を全て取得
        "_fields":  "id,title,date,slug,status,link",
        "per_page": 100,
        "page":     1,
    }

    all_posts: list[dict] = []
    while True:
        resp = requests.get(endpoint, params=params, auth=auth, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for p in batch:
            raw_title = p.get("title", "")
            title = raw_title["rendered"] if isinstance(raw_title, dict) else raw_title
            all_posts.append({
                "id":     p.get("id"),
                "title":  title,
                "slug":   p.get("slug", ""),
                "date":   p.get("date", ""),
                "status": p.get("status", ""),
                "link":   p.get("link", ""),
            })
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        if params["page"] >= total_pages:
            break
        params["page"] += 1

    # ステータス内訳をログ出力
    from collections import Counter
    status_counts = Counter(p["status"] for p in all_posts)
    breakdown = " / ".join(f"{s}={c}" for s, c in sorted(status_counts.items()))
    log.info(f"[wp] 記事取得: 計{len(all_posts)}件 ({breakdown})")
    return all_posts


def _normalize_title(title: str) -> str:
    """タイトルを比較用に正規化する（年号・順位・記号・大小文字を統一）。"""
    import re
    import unicodedata
    t = unicodedata.normalize("NFKC", title)
    t = re.sub(r'20\d{2}年?', '', t)                          # 年号除去（2020〜2099）
    t = re.sub(r'\d+選', '', t)                               # N選除去
    t = re.sub(r'[【】「」『』\[\](（）)！!？?。、，,・~〜]', '', t)  # 記号除去
    t = t.lower().strip()
    return t


def _extract_core_keyword(text: str, stop_words: list[str]) -> str:
    """
    ストップワードを除去してコアキーワードを抽出する。

    NFKC正規化 + 小文字化した後にストップワードを除去し、
    余分な空白を詰めて返す。

    Example:
        _extract_core_keyword("aiボイスレコーダー アプリ iphone", ["アプリ","iphone"])
        → "aiボイスレコーダー"
    """
    import re, unicodedata
    t = unicodedata.normalize("NFKC", text).lower()
    for sw in stop_words:
        sw_n = unicodedata.normalize("NFKC", sw).lower()
        t = re.sub(re.escape(sw_n), " ", t)
    return " ".join(t.split())


def _title_similarity(a: str, b: str) -> float:
    """文字バイグラムの Jaccard 類似度（0.0〜1.0）を返す。"""
    def bigrams(s: str) -> set[str]:
        return {s[i:i+2] for i in range(len(s) - 1)} if len(s) >= 2 else set(s)

    bg_a = bigrams(a)
    bg_b = bigrams(b)
    if not bg_a and not bg_b:
        return 1.0
    if not bg_a or not bg_b:
        return 0.0
    return len(bg_a & bg_b) / len(bg_a | bg_b)


def _check_duplicate(
    candidate: dict,
    wp_posts: list[dict],
    recent_cutoff: datetime,
    stop_words: list[str] | None = None,
) -> tuple[bool, str]:
    """
    候補が WP公開記事と重複するかチェックする。

    Check order:
        0. コアKW重複（最優先）: ストップワード除去後のコアが一致
        1. 同一キーワード: スラグまたはタイトルにキーワードが完全含まれる
        2. 同一タイトル: 正規化後の完全一致
        3. 近似タイトル: Jaccard bigram >= TITLE_SIM_THRESHOLD
        4. 直近 WP_RECENT_DAYS 日以内の記事のスラグと2語以上重複

    Returns:
        (is_duplicate: bool, reason: str)
    """
    _stop     = stop_words or []
    kw_lower  = candidate["keyword"].lower()
    norm_kw   = _normalize_title(candidate["keyword"])
    kw_words  = set(kw_lower.split())
    core_kw   = _extract_core_keyword(kw_lower, _stop) if _stop else ""
    # コアKWが短すぎる場合はテーマ重複チェックをスキップ（誤検知防止）
    core_valid = bool(core_kw) and len(core_kw.replace(" ", "")) >= 4

    # カニバリ検知用：2文字以上の意味語トークンを抽出
    # 助詞・助動詞相当の短語・ストップワードを除外して残った語で重複判定
    _TRIVIAL = {"する", "できる", "ない", "ある", "なる", "いる", "もの",
                "こと", "ため", "から", "まで", "より", "など", "ので",
                "では", "には", "との", "への", "での", "とは", "について",
                "について", "として", "による", "方法", "やり方", "一覧"}
    kw_tokens = [
        w for w in kw_lower.split()
        if len(w) >= 2 and w not in _stop and w not in _TRIVIAL
    ]
    # カニバリ判定閾値：トークン数に応じて動的に設定
    #   2語 → 2語全一致, 3語 → 2語以上, 4語以上 → 3語以上
    if len(kw_tokens) >= 2:
        kanibari_threshold = max(2, min(3, len(kw_tokens) - 1))
    else:
        kanibari_threshold = 999  # 1語以下は判定しない

    recent_posts = []
    for p in wp_posts:
        title_raw  = p["title"]
        slug       = p["slug"].replace("-", " ")
        norm_title = _normalize_title(title_raw)
        title_lower = title_raw.lower()

        # (0) コアKW重複（最優先）─ ストップワード除去後のコア一致
        if _stop and core_valid:
            core_title = _extract_core_keyword(title_raw, _stop)
            # 候補のコアが既存記事タイトルに含まれる、または逆方向
            if (core_kw in core_title
                    or (len(core_title.replace(" ", "")) >= 4 and core_title in core_kw)):
                return True, f"コアKW重複: 「{title_raw[:40]}」(core: {core_kw!r})"

        # (1) 同一キーワード
        if kw_lower in title_lower or kw_lower in slug:
            return True, f"同一キーワード: 「{title_raw[:40]}」"

        # (2) 同一タイトル（正規化後）
        if norm_kw and norm_title and norm_kw == norm_title:
            return True, f"同一タイトル: 「{title_raw[:40]}」"

        # (3) 近似タイトル
        sim = _title_similarity(norm_kw, norm_title)
        if sim >= TITLE_SIM_THRESHOLD:
            return True, f"近似タイトル({sim:.2f}): 「{title_raw[:40]}」"

        # (5) カニバリ検知：意味語トークンが閾値以上タイトルに含まれる
        if kw_tokens:
            token_overlap = [w for w in kw_tokens if w in title_lower]
            if len(token_overlap) >= kanibari_threshold:
                return True, (
                    f"カニバリ({len(token_overlap)}/{len(kw_tokens)}語重複"
                    f" {token_overlap}): 「{title_raw[:40]}」"
                )

        # 直近記事リストを作成（(4)で使用）
        try:
            post_date = datetime.fromisoformat(p["date"])
            if post_date >= recent_cutoff:
                recent_posts.append((p, slug))
        except ValueError:
            pass

    # (4) 直近 WP_RECENT_DAYS 日以内の記事とスラグ語が2語以上重複
    for p, slug in recent_posts:
        slug_words = set(slug.split())
        overlap = slug_words & kw_words
        if len(overlap) >= 2:
            return True, f"直近{WP_RECENT_DAYS}日重複: 「{p['title'][:40]}」"

    return False, ""


def _check_title_after_generation(
    generated_title: str,
    wp_posts: list[dict],
) -> tuple[bool, str]:
    """
    生成後のタイトルと既存WP記事タイトルの類似度チェック。

    キーワード段階での重複チェック（_check_duplicate）は
    「短いキーワード vs 長いタイトル」の比較なので Jaccard が低くなりやすい。
    生成後は「タイトル vs タイトル」で比較するため精度が高い。

    Returns:
        (is_duplicate: bool, matched_title: str)
    """
    norm_new = _normalize_title(generated_title)
    for p in wp_posts:
        norm_existing = _normalize_title(p["title"])
        # 完全一致は閾値によらず必ずブロック
        if norm_new == norm_existing:
            return True, p["title"]
        sim = _title_similarity(norm_new, norm_existing)
        if sim >= POST_GEN_SIM_THRESHOLD:
            return True, p["title"]
    return False, ""


# ═══════════════════════════════════════════════════════════════
# TREND KEYWORD FETCHER
# Googleトレンド (RSS) + はてなブックマーク hotentry から取得
# ═══════════════════════════════════════════════════════════════
def fetch_trend_keywords() -> list[dict]:
    """
    Googleトレンド JP (RSS) + はてなブックマーク IT hotentry から
    トレンドキーワードを取得する。

    Returns:
        [{"keyword": str, "volume": 0, "seo_difficulty": None,
          "competition": None, "priority": False, "_type": "trend"}, ...]
    """
    if not FEATURES.get("trend_auto_fetch", True):
        return []
    import requests
    import xml.etree.ElementTree as ET

    raw_keywords: list[str] = []

    # ── Google Trends JP (デイリートレンド RSS) ────────────────
    try:
        resp = requests.get(
            "https://trends.google.com/trending/rss?geo=JP",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; generate_lite/1.0)"},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            if title:
                raw_keywords.append(title)
        log.info(f"[trend] Google Trends JP: {len(raw_keywords)}件")
    except Exception as e:
        log.warning(f"[trend] Google Trends 取得失敗: {e}")

    gt_count = len(raw_keywords)

    # ── はてなブックマーク IT hotentry (RSS 1.0) ─────────────
    try:
        resp = requests.get(
            "https://b.hatena.ne.jp/hotentry/it.rss",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; generate_lite/1.0)"},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        # RSS 1.0 は名前空間付き
        ns = "http://purl.org/rss/1.0/"
        items = root.findall(f"{{{ns}}}item") or root.findall(".//item")
        for item in items:
            title = (
                item.findtext(f"{{{ns}}}title", "")
                or item.findtext("title", "")
            ).strip()
            if title:
                # 長すぎるタイトルは先頭40文字
                raw_keywords.append(title[:40] if len(title) > 40 else title)
        log.info(f"[trend] はてなブックマーク IT: {len(raw_keywords) - gt_count}件")
    except Exception as e:
        log.warning(f"[trend] はてなブックマーク 取得失敗: {e}")

    # カンマ区切り複数ワードの場合は先頭1語のみ使用（Google Trends 複合クエリ対策）
    import re as _re
    cleaned: list[str] = []
    for kw in raw_keywords:
        kw = kw.strip()
        if "," in kw:
            kw = kw.split(",")[0].strip()
        # WP タグAPI 400エラー防止: 特殊引用符・括弧類を除去
        kw = _re.sub(r'[「」『』【】〔〕《》〈〉""''\u2018\u2019\u201c\u201d・…—―]', '', kw).strip()
        if kw:
            cleaned.append(kw)

    # 重複除去
    seen: set[str] = set()
    unique: list[str] = []
    for kw in cleaned:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)

    log.info(f"[trend] トレンドKW 計: {len(unique)}件（重複除去後）")

    return [
        {
            "keyword":        kw,
            "volume":         0,
            "seo_difficulty": None,
            "competition":    None,
            "priority":       False,
            "_type":          "trend",
        }
        for kw in unique
    ]


# ═══════════════════════════════════════════════════════════════
# ARTICLE TYPE DISTRIBUTOR
# ═══════════════════════════════════════════════════════════════
def _distribute_articles(n: int, weights: dict[str, float]) -> dict[str, int]:
    """
    n 件の記事を weights の比率で各タイプに配分する（largest remainder method）。

    Example:
        _distribute_articles(3, {"longtail":0.5, "trend":0.3, "monetize":0.2})
        → {"longtail": 1, "trend": 1, "monetize": 1}
    """
    if not weights:
        return {"longtail": n}

    total = sum(weights.values())
    norm  = {k: v / total for k, v in weights.items()}
    floors = {k: int(n * v) for k, v in norm.items()}
    remainders = {k: (n * v) - floors[k] for k, v in norm.items()}

    remaining = n - sum(floors.values())
    for k in sorted(remainders, key=lambda x: remainders[x], reverse=True):
        if remaining <= 0:
            break
        floors[k] += 1
        remaining -= 1

    return floors


def _group_balanced_pool(
    candidates: list[dict],
    stop_words: list[str] | None,
    top_n: int = TOP_N_CANDIDATES,
) -> list[dict]:
    """
    候補をコアKWでグループ化し、各グループから均等にラウンドロビン抽出する。
    グループ内は volume 降順→ランダムシャッフル。
    特定グループへの偏り（AIボイスレコーダー系など）を解消する。
    """
    import random
    from collections import defaultdict

    sw = stop_words or []
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        core = _extract_core_keyword(c["keyword"].lower(), sw)
        # コアKWが短すぎる場合はキーワード先頭1語をグループキーにする
        if len(core) < 4:
            core = c["keyword"].split()[0].lower() if c["keyword"].split() else core
        groups[core].append(c)

    # 各グループ内をvol降順にして、上位から選ぶ（一定のランダム性を保つ）
    for g in groups.values():
        g.sort(key=lambda x: -x["volume"])

    # ラウンドロビン：グループを1件ずつ循環して top_n 件になるまで取り出す
    pool: list[dict] = []
    group_iters = {k: iter(v) for k, v in groups.items()}
    group_keys  = list(groups.keys())
    random.shuffle(group_keys)  # グループ順序もランダム化
    while len(pool) < top_n:
        advanced = False
        for key in group_keys:
            if len(pool) >= top_n:
                break
            it = group_iters.get(key)
            if it is None:
                continue
            try:
                pool.append(next(it))
                advanced = True
            except StopIteration:
                group_iters.pop(key)
        if not advanced:
            break  # 全グループ枯渇

    log.debug(f"[group_pool] グループ数: {len(groups)}件 → pool: {len(pool)}件")
    return pool


def filter_duplicates(
    candidates: list[dict],
    wp_posts: list[dict],
    n: int,
    stop_words: list[str] | None = None,
    group_balanced: bool = True,
) -> list[dict]:
    """
    重複を除外して n 件のキーワードを返す。

    ・月間検索数降順ソート後 TOP_N_CANDIDATES 件をプールとしてシャッフル評価。
    ・priority=True の候補は先頭に置いて優先評価する。
    ・重複候補はログに残してスキップし、残り候補から補充する。
    ・n 件確保できない場合はその時点で確保できた件数を返す。
    """
    import random
    from datetime import timedelta

    # aim優先度 (_priority_level) 降順 → volume 降順でソートして先頭評価
    # now=4 > future=3 > monetize=2 > aim/add=1 > 未指定=0
    high_pool = sorted(
        [c for c in candidates if c.get("_priority_level", 0) > 0],
        key=lambda x: (-x.get("_priority_level", 0), -x["volume"]),
    )
    low_priority = [c for c in candidates if c.get("_priority_level", 0) == 0]
    if group_balanced:
        # グループ均等選定（AIボイスレコーダー系への偏りを解消）
        normal_pool = _group_balanced_pool(low_priority, stop_words, top_n=TOP_N_CANDIDATES)
    else:
        normal_sorted = sorted(low_priority, key=lambda x: x["volume"], reverse=True)
        normal_pool   = normal_sorted[:TOP_N_CANDIDATES]
        random.shuffle(normal_pool)
    pool = high_pool + normal_pool

    if high_pool:
        by_aim: dict[str, int] = {}
        for c in high_pool:
            lv = c.get("_aim", "?")
            by_aim[lv] = by_aim.get(lv, 0) + 1
        log.info(f"[dup_check] 優先候補: {len(high_pool)}件 {by_aim} を先頭評価")

    recent_cutoff = datetime.now() - timedelta(days=WP_RECENT_DAYS)

    chosen:   list[dict] = []
    excluded: list[dict] = []

    for c in pool:
        if len(chosen) >= n:
            break
        is_dup, reason = _check_duplicate(c, wp_posts, recent_cutoff, stop_words=stop_words)
        if is_dup:
            log.info(f"[dup_check] 除外: 「{c['keyword']}」 → {reason}")
            excluded.append({**c, "reason": reason})
        else:
            log.debug(f"[dup_check] OK: 「{c['keyword']}」")
            chosen.append(c)

    log.info(
        f"[dup_check] 完了: 選定={len(chosen)}件 / 除外={len(excluded)}件"
        f" (pool={len(pool)}件, 要求={n}件)"
    )
    if len(chosen) < n:
        log.warning(f"[dup_check] 目標{n}件に対し{len(chosen)}件のみ確保（候補不足）")

    return chosen


# ═══════════════════════════════════════════════════════════════
# STEP 2: キーワード選定
# Phase 2: 記事タイプ別・重複チェック付きに拡張予定
# ═══════════════════════════════════════════════════════════════
def select_keyword(
    candidates: list[dict],
    article_type: ArticleType = ArticleType.LONGTAIL,
) -> dict:
    """
    候補からキーワードを1件選定する。

    現在: 月間検索数上位 TOP_N_CANDIDATES 件からランダム選択。
    Phase 2: article_type 別ロジック・重複チェック付きに拡張。

    Returns:
        {"keyword": str, "volume": int, ...}
    """
    import random

    if not candidates:
        raise ValueError("候補キーワードが0件です")

    # Phase 2: 投稿済み重複チェック
    if FEATURES["duplicate_check"]:
        raise NotImplementedError("重複チェックはPhase 2で実装予定")

    # Phase 2: 記事タイプ別の選定ロジック
    # TREND     → 直近7日間のX検索数・急上昇スコアで重み付け
    # MONETIZE  → CPC / 競合性スコアで重み付け
    # LONGTAIL  → 現在の実装（月間検索数上位からランダム）

    sorted_candidates = sorted(candidates, key=lambda x: x["volume"], reverse=True)
    pool   = sorted_candidates[:TOP_N_CANDIDATES]
    chosen = random.choice(pool)

    log.info(
        f"[select] 選定: 「{chosen['keyword']}」"
        f" vol={chosen['volume']:,}"
        f" seo={chosen['seo_difficulty'] or 'N/A'}"
        f" comp={chosen['competition'] or 'N/A'}"
        f" (pool={len(pool)}件)"
    )
    return chosen


def select_keywords(
    candidates: list[dict],
    n: int = ARTICLE_COUNT,
    article_type: ArticleType = ArticleType.LONGTAIL,
    wp_posts: list[dict] | None = None,
    stop_words: list[str] | None = None,
) -> list[dict]:
    """
    候補からキーワードを n 件選定する（重複なし）。

    FEATURES["duplicate_check"] = True の場合は WP公開記事との重複を除外し、
    常に n 件確保できるよう残り候補から補充する。
    """
    import random

    if not candidates:
        raise ValueError("候補キーワードが0件です")

    # 重複チェックモード
    if FEATURES["duplicate_check"] and wp_posts is not None:
        chosen = filter_duplicates(candidates, wp_posts, n, stop_words=stop_words)
    else:
        n = min(n, len(candidates))
        sorted_candidates = sorted(candidates, key=lambda x: x["volume"], reverse=True)
        pool   = sorted_candidates[:TOP_N_CANDIDATES]
        chosen = random.sample(pool, min(n, len(pool)))

    log.info(f"[select] {len(chosen)}件選定 (要求={n}件)")
    for i, c in enumerate(chosen, 1):
        log.info(
            f"[select]   {i}. 「{c['keyword']}」"
            f" vol={c['volume']:,} seo={c['seo_difficulty'] or 'N/A'}"
            f" comp={c['competition'] or 'N/A'}"
        )
    return chosen


# ═══════════════════════════════════════════════════════════════
# STEP 3: 記事生成
# ─────────────────────────────────────────────────────────────
# 記事タイプ → target_length 解決ヘルパー
# ─────────────────────────────────────────────────────────────

def _resolve_target_length(target_length: int | dict, article_type: str) -> int:
    """
    BlogConfig.target_length（int or dict）と article_type から
    生成に使う目標文字数を返す。

    dict の場合: キーは大文字 MONETIZE / LONGTAIL / FUTURE / TREND など。
    "trend" は "FUTURE" にフォールバック（キーがなければ最大値）。
    """
    if isinstance(target_length, int):
        return target_length
    if not isinstance(target_length, dict):
        return 9000

    key = article_type.upper()
    normalized = {k.upper(): int(v) for k, v in target_length.items()}

    if key in normalized:
        return normalized[key]
    # TREND → FUTURE フォールバック（短め記事として扱う）
    if key == "TREND" and "FUTURE" in normalized:
        return normalized["FUTURE"]
    # どのキーにもマッチしなければ最大値（品質優先）
    return max(normalized.values())


# 既存の generate_article() をそのまま利用
# ═══════════════════════════════════════════════════════════════
def generate(
    keyword: str,
    volume: int,
    blog_cfg: BlogConfig | None = None,
    sub_keywords: list[str] | None = None,
    article_type: str = "longtail",
    asp_list: list[dict] | None = None,
    forced_title: str | None = None,
) -> dict:
    """
    記事を生成して dict で返す。
    blog_cfg が指定された場合はそのブログの設定（fact_check・target_length）を反映する。
    article_type に応じて target_length を解決し、H3本数・FAQ・max_tokensを切り替える。
    asp_list が渡された場合はASP案件リンクをプロンプトに注入する。
    blog_cfg.guide_links が設定されている場合は内部誘導リンクをプロンプトに注入する。
    """
    fact_check    = blog_cfg.fact_check if blog_cfg is not None else True
    raw_tl        = blog_cfg.target_length if blog_cfg is not None else 9000
    target_length = _resolve_target_length(raw_tl, article_type)
    guide_links   = blog_cfg.guide_links if blog_cfg is not None else {}

    log.info(
        f"[generate] 生成開始: 「{keyword}」(vol:{volume:,})"
        f" fact_check={fact_check} target_length={target_length:,}字"
        + (f"  サブKW:{len(sub_keywords)}件" if sub_keywords else "")
        + (f"  誘導リンク:{len([v for v in guide_links.values() if v])}件" if guide_links else "")
    )
    article = generate_article(keyword, volume, sub_keywords=sub_keywords,
                               enable_fact_check=fact_check,
                               target_length=target_length,
                               article_type=article_type,
                               asp_list=asp_list,
                               guide_links=guide_links or None,
                               forced_title=forced_title)

    # ── マイパターン CTA 挿入（ブログにパターンがある場合のみ）──
    if blog_cfg:
        blog_name = blog_cfg.name
        if blog_name not in _wp_patterns_cache:
            try:
                _wp_patterns_cache[blog_name] = fetch_patterns(blog_cfg)
            except Exception as e:
                log.warning(f"[generate] マイパターン取得失敗（スキップ）: {e}")
                _wp_patterns_cache[blog_name] = []
        patterns = _wp_patterns_cache[blog_name]
        if patterns:
            matched = match_pattern(keyword, patterns)
            if matched:
                article["content"] = insert_pattern_cta(article["content"], matched)
                log.info(f"[generate] パターンCTA挿入: 「{matched.title}」(ID:{matched.id})")
            else:
                log.debug(f"[generate] マッチするパターンなし（KW={keyword!r}）")

    # 外部リンク死活チェック（存在しないWikipedia等のリンクを除去）
    article["content"] = _remove_dead_external_links(article["content"])

    log.info(f"[generate] 完了: 「{article['title']}」")
    return article


# ═══════════════════════════════════════════════════════════════
# STEP 4: WordPress投稿
# Phase 2: 画像生成・CTA挿入・シートフラグ更新を追加予定
# ═══════════════════════════════════════════════════════════════
def post(article: dict, dry_run: bool = False,
         blog_cfg: BlogConfig | None = None,
         asp_list: list[dict] | None = None) -> dict:
    """
    WordPress に下書きとして投稿する。
    blog_cfg が指定された場合は一時的に WP 認証情報を切り替えて投稿する。
    Phase 1: テキストのみ・画像なし・CTA注入なし。
    Phase 2: FEATURES["image_generation"] = True で画像生成を追加。
    Phase 2: FEATURES["sheets_update"] = True でシートフラグ書き込みを追加。
    """
    if dry_run:
        log.info(f"[post] DRY-RUN スキップ: 「{article['title']}」")
        return {"id": None, "url": "", "edit_url": "", "status": "dry-run"}

    # ブログ別 WP 認証情報・投稿方式をコンテキストにセット（全モジュール共有）
    if blog_cfg:
        wp_context.set_context(
            blog_cfg.wp_url,
            blog_cfg.wp_username,
            blog_cfg.wp_app_password,
            wp_post_status=blog_cfg.wp_post_status,
            candidate_ss_id=blog_cfg.candidate_ss_id,
            candidate_sheet=blog_cfg.candidate_sheet,
            image_style=blog_cfg.image_style,
            asp_ss_id=blog_cfg.asp_ss_id,
            default_fallback_category=blog_cfg.extra.get("default_fallback_category", ""),
            blog_meta={
                "display_name":  blog_cfg.display_name,
                "wp_url":        blog_cfg.wp_url,
                "genre":         blog_cfg.genre,
                "site_purpose":  blog_cfg.site_purpose,
                "target":        blog_cfg.target,
                "writing_taste": (
                    blog_cfg.writing_taste
                    + ("\n" + blog_cfg.extra.get("content_notes", "")
                       if blog_cfg.extra.get("content_notes") else "")
                ),
                "genre_detail":  blog_cfg.genre_detail,
                "search_intent": blog_cfg.search_intent,
            },
        )
        log.info(f"[post] 投稿方式: {blog_cfg.wp_post_status}")

    try:
        if FEATURES["image_generation"]:
            # 画像生成 → post_article_with_image（アイキャッチ設定・H2画像注入を含む）
            image_bytes: bytes | None = None
            keyword = article.get("keyword", "")
            try:
                image_bytes = generate_image_for_article(
                    keyword=keyword,
                    article_type=article.get("_article_type", ""),
                )
                log.info(f"[post] 画像生成完了: {len(image_bytes):,} bytes")
            except Exception as img_err:
                log.warning(f"[post] 画像生成スキップ（続行）: {img_err}")

            # asp_links: blog_config.json の静的リンク + シートからの動的リンク をマージ
            asp_links  = dict(blog_cfg.asp_links) if blog_cfg else {}
            if asp_list:
                from modules.asp_fetcher import to_asp_dict
                asp_links.update(to_asp_dict(asp_list))
            stop_words = blog_cfg.stop_words if blog_cfg else []
            result = post_article_with_image(article, image_bytes=image_bytes,
                                             asp_links=asp_links, stop_words=stop_words)
        else:
            result = create_post(article, featured_media_id=None)
    finally:
        wp_context.clear_context()

    log.info(f"[post] WP投稿完了: ID={result['id']} → {result['edit_url']}")

    # Phase 2: 投稿済みフラグをシートに書き込む
    if FEATURES["sheets_update"]:
        raise NotImplementedError("シート更新はPhase 2で実装予定")

    return {**result, "status": "success"}


# ═══════════════════════════════════════════════════════════════
# BLOG RUNNER
# ブログ1件分の記事生成フロー（fetch → select → generate → post）
# ═══════════════════════════════════════════════════════════════
def run_blog(
    blog_cfg: BlogConfig,
    dry_run: bool = False,
    keyword: str | None = None,
    volume: int = 0,
    count: int | None = None,
    forced_title: str | None = None,
) -> list[dict]:
    """
    1ブログ分の記事生成フローを実行して結果リストを返す。

    Args:
        blog_cfg : ブログ設定
        dry_run  : True のとき WP 投稿をスキップ
        keyword  : 直接指定するキーワード（None のときはシートから選定）
        volume   : keyword 指定時の月間検索数
        count    : 生成記事数（None のとき blog_cfg.article_count を使用）
    """
    import time

    n_articles = count if count is not None else blog_cfg.article_count
    stop_words = blog_cfg.stop_words  # コアKW正規化用（空リストのとき無効）

    log.info(f"  genre            : {blog_cfg.genre}")
    log.info(f"  fact_check       : {blog_cfg.fact_check}")
    log.info(f"  article_type_mix : {FEATURES['article_type_mix']}")
    log.info(f"  stop_words       : {stop_words or '(なし)'}")
    log.info(f"  article_count    : {n_articles}  dry_run: {dry_run}")

    # ── ASP案件リスト読み込み（ブログ別SS の ASP案件マスターシートから）──
    asp_list: list[dict] = []
    try:
        from modules.asp_fetcher import fetch_asp_links
        asp_list = fetch_asp_links(blog_cfg.display_name)
    except Exception as asp_err:
        log.warning(f"[{blog_cfg.name}] ASP案件読み込みスキップ（続行）: {asp_err}")

    # ── Step 1: キーワード選定 ──────────────────────────
    sub_keywords: list[str] = []  # vol<30のサブKW（記事本文に盛り込む）

    # WP記事取得（公開・下書き・非公開。全分岐共通で実行）
    wp_posts: list[dict] | None = None
    if FEATURES["duplicate_check"]:
        try:
            wp_posts = fetch_wp_posts(blog_cfg=blog_cfg)
        except Exception as e:
            log.warning(f"[{blog_cfg.name}] WP記事取得失敗（重複チェックなしで続行）: {e}")

    if keyword:
        targets = [{"keyword": keyword, "volume": volume,
                    "seo_difficulty": None, "competition": None,
                    "priority": False, "_type": "longtail", "_aim": ""}]
        log.info(f"[{blog_cfg.name}] キーワード直接指定: 「{keyword}」")
        n_candidates = 1
    else:
        if FEATURES["article_type_mix"]:
            # ── 記事タイプ配分モード ──────────────────────
            weights    = blog_cfg.article_type_weights
            dist       = _distribute_articles(n_articles, weights)
            log.info(f"[{blog_cfg.name}] 記事タイプ配分: {dist}  (weights={weights})")

            sheet_candidates, sub_keywords = fetch_candidates(ArticleType.LONGTAIL, blog_cfg=blog_cfg)
            n_candidates     = len(sheet_candidates)
            targets: list[dict] = []
            used_kws: set[str] = set()

            # --- LONGTAIL ---
            if dist.get("longtail", 0) > 0:
                lt_pool = [c for c in sheet_candidates if c["keyword"] not in used_kws]
                lt_sel  = select_keywords(lt_pool, n=dist["longtail"],
                                          article_type=ArticleType.LONGTAIL, wp_posts=wp_posts,
                                          stop_words=stop_words)
                for kw in lt_sel:
                    kw["_type"] = "longtail"
                    used_kws.add(kw["keyword"])
                targets.extend(lt_sel)
                log.info(f"[{blog_cfg.name}] LONGTAIL選定: {len(lt_sel)}件")

            # --- TREND ---
            if dist.get("trend", 0) > 0:
                try:
                    trend_cands = fetch_trend_keywords()
                    tr_sel = select_keywords(trend_cands, n=dist["trend"],
                                             article_type=ArticleType.TREND, wp_posts=wp_posts,
                                             stop_words=stop_words)
                    for kw in tr_sel:
                        kw["_type"] = "trend"
                        used_kws.add(kw["keyword"])
                    targets.extend(tr_sel)
                    log.info(f"[{blog_cfg.name}] TREND選定: {len(tr_sel)}件")
                except Exception as e:
                    log.warning(f"[{blog_cfg.name}] トレンドKW取得失敗 → LONGTAILで補充: {e}")
                    lt_extra = [c for c in sheet_candidates if c["keyword"] not in used_kws]
                    lt_fallback = select_keywords(lt_extra, n=dist["trend"],
                                                  article_type=ArticleType.LONGTAIL, wp_posts=wp_posts,
                                                  stop_words=stop_words)
                    for kw in lt_fallback:
                        kw["_type"] = "longtail"
                        used_kws.add(kw["keyword"])
                    targets.extend(lt_fallback)

            # --- MONETIZE ---
            if dist.get("monetize", 0) > 0:
                # 競合性が高いキーワード（comp >= 50）を優先、なければ全体から
                mo_pool = [c for c in sheet_candidates
                           if c["keyword"] not in used_kws
                           and (c.get("competition") or 0) >= 50]
                if len(mo_pool) < dist["monetize"]:
                    mo_pool = [c for c in sheet_candidates if c["keyword"] not in used_kws]
                mo_sel = select_keywords(mo_pool, n=dist["monetize"],
                                         article_type=ArticleType.MONETIZE, wp_posts=wp_posts,
                                         stop_words=stop_words)
                for kw in mo_sel:
                    kw["_type"] = "monetize"
                    used_kws.add(kw["keyword"])
                targets.extend(mo_sel)
                log.info(f"[{blog_cfg.name}] MONETIZE選定: {len(mo_sel)}件")

        else:
            # ── LONGTAIL 固定モード（従来動作）────────────
            sheet_candidates, sub_keywords = fetch_candidates(ArticleType.LONGTAIL, blog_cfg=blog_cfg)
            n_candidates = len(sheet_candidates)
            targets = select_keywords(
                sheet_candidates, n=n_articles, article_type=ArticleType.LONGTAIL,
                wp_posts=wp_posts, stop_words=stop_words
            )
            for kw in targets:
                kw["_type"] = "longtail"

    log.info(f"[{blog_cfg.name}] 候補: {n_candidates}件 / 選定: {len(targets)}件 / 生成予定: {n_articles}件")

    # ── Step 2-3: 記事生成 → WP投稿（失敗しても次へ続行）──
    results:   list[dict] = []
    n_success = 0
    n_error   = 0
    n_skip    = 0

    # 処理開始前に安全装置チェック（STOP ファイル / 日次・時間上限）
    check_stop()
    summary = daily_summary()
    log.info(
        f"[api_guard] 本日の使用量: ${summary['cost_usd']:.4f} / ¥{summary['cost_jpy']:.0f}"
        f" ({summary['calls']}回呼び出し)"
    )

    for i, chosen in enumerate(targets, 1):
        article_type_label = chosen.get("_type", "longtail")
        log.info(f"{'─' * 60}")
        log.info(
            f"[{blog_cfg.name}] [{i}/{len(targets)}]"
            f" [{article_type_label.upper()}] 「{chosen['keyword']}」 vol={chosen['volume']:,}"
            + (f" ★{chosen['_aim'].upper()}" if chosen.get("_aim") else "")
        )
        log.info(f"{'─' * 60}")

        item: dict = {
            "started_at":   datetime.now().isoformat(),
            "blog":         blog_cfg.name,
            "dry_run":      dry_run,
            "keyword":      chosen["keyword"],
            "volume":       chosen["volume"],
            "article_type": article_type_label,
            "status":       "error",
        }

        try:
            # サブKWを取得（新フォーマット: _sub_kws、旧フォーマット: fuzzyマッチ）
            if "_sub_kws" in chosen:
                related_sub = chosen["_sub_kws"][:20]  # 新フォーマット: 紐付け済みサブKW
            else:
                kw_core = _extract_core_keyword(chosen["keyword"].lower(), stop_words)
                related_sub = [
                    s for s in sub_keywords
                    if kw_core and kw_core in s.lower()
                ][:20]

            article     = generate(chosen["keyword"], chosen["volume"],
                                   blog_cfg=blog_cfg, sub_keywords=related_sub or None,
                                   article_type=article_type_label,
                                   asp_list=asp_list or None,
                                   forced_title=forced_title)
            # 記事タイプ・KWステータスを article dict に付与（シート書き込み用）
            article["_article_type"] = article_type_label
            article["_kw_status"]    = chosen.get("_aim", "")

            # ── 生成後タイトル重複チェック ──────────────────────────
            # タイトル強制指定時はスキップ（ユーザーが明示的に指定したため）
            if wp_posts and not forced_title:
                is_dup_post, dup_title = _check_title_after_generation(
                    article["title"], wp_posts
                )
                if is_dup_post:
                    raise DuplicateSkipError(
                        f"タイトル重複のため投稿スキップ: "
                        f"「{article['title'][:35]}」≈「{dup_title[:35]}」"
                    )

            post_result = post(article, dry_run=dry_run, blog_cfg=blog_cfg, asp_list=asp_list)

            # 投稿成功後にメモリ内 wp_posts を更新（同セッション内の重複防止）
            if wp_posts is not None:
                wp_posts.append({
                    "id":     post_result.get("id", 0),
                    "title":  article["title"],
                    "slug":   "",
                    "date":   datetime.now().isoformat(),
                    "status": blog_cfg.wp_post_status,
                })

            item.update({
                "status":      post_result["status"],
                "title":       article["title"],
                "post_id":     post_result.get("id"),
                "edit_url":    post_result.get("edit_url", ""),
                "finished_at": datetime.now().isoformat(),
            })
            n_success += 1
            log.info(f"[{blog_cfg.name}] [{i}/{len(targets)}] ✅ 完了: 「{article['title']}」")

        except DuplicateSkipError as e:
            item["status"] = "skipped_duplicate"
            item["error"]  = str(e)
            n_skip += 1
            log.warning(f"[{blog_cfg.name}] [{i}/{len(targets)}] ⏭️ 重複スキップ: {e}")
            # シートに「カニバリスキップ」を記録して次回の再選択を防ぐ
            try:
                from modules.sheets_updater import mark_duplicate_skip
                mark_duplicate_skip(item.get("keyword", ""), reason=str(e))
            except Exception as _se:
                log.warning(f"[{blog_cfg.name}] シートへのスキップ記録失敗（続行）: {_se}")

        except Exception as e:
            item["error"] = str(e)
            n_error += 1
            log.error(f"[{blog_cfg.name}] [{i}/{len(targets)}] ❌ エラー（続行）: {e}")

        finally:
            _log_result(item)
            results.append(item)

        if i < len(targets):
            log.info(f"[{blog_cfg.name}] {INTER_ARTICLE_WAIT}秒待機...")
            time.sleep(INTER_ARTICLE_WAIT)

    log.info(
        f"[{blog_cfg.name}] 完了: 成功={n_success}件 / 重複スキップ={n_skip}件 / 失敗={n_error}件 / 合計={len(targets)}件"
    )
    return results


# ═══════════════════════════════════════════════════════════════
# KANIKABARI CHECK（--kanikabari モード）
# ─────────────────────────────────────────────────────────────
# シート内キーワード間クラスタリング + WP既存記事との重複判定を行い、
# D列(判定)・E列(統合先KW)・G列(ステータス)に結果を書き込む。
# ─────────────────────────────────────────────────────────────
INTRA_CLUSTER_THRESHOLD       = 0.20  # シート内 Jaccard 閾値
KANIKABARI_WP_SKIP_HIGH       = 0.55  # ほぼ同一タイトル → カニバリスキップ
KANIKABARI_WP_SKIP_MED        = 0.35  # 意図一致・高類似 → カニバリスキップ
KANIKABARI_WP_TOGO_THRESH     = 0.25  # 意図一致・中類似 → 統合対象（追記）
KANIKABARI_WP_REVIEW_THRESH   = 0.20  # 弱類似・意図曖昧 → 要確認

# 末尾修飾語（検索意図の主軸ではない語）— ベースKW抽出時に除去する
_BASE_KW_MODIFIERS: frozenset[str] = frozenset({
    # 方法・手順系
    "方法", "やり方", "仕方", "手順", "手続き", "手続",
    "始め方", "辞め方", "やめ方", "選び方", "使い方", "作り方",
    "書き方", "読み方", "聞き方", "伝え方", "話し方", "見つけ方",
    # 評価・口コミ系
    "相場", "口コミ", "評判", "レビュー", "評価", "体験談", "感想",
    # 解説系
    "とは", "解説", "まとめ", "ガイド", "一覧", "比較", "違い", "特徴",
    # 理由・原因系
    "理由", "原因", "なぜ", "なんで",
    # 注意・ポイント系
    "注意点", "注意", "ポイント", "コツ", "デメリット", "メリット", "問題",
    # 解決系
    "解決策", "対処法", "対処", "解決", "改善方法", "改善",
    # ランキング・おすすめ系
    "ランキング", "おすすめ", "人気",
    # 費用・料金系
    "手数料", "料金", "費用", "値段", "価格",
})

# 末尾サフィックス（これで終わるトークンは修飾語扱い）
_BASE_KW_MODIFIER_SUFFIXES: tuple[str, ...] = (
    "たくない", "できない", "わからない", "づらい", "にくい",
    "すぎる", "すぎ", "したい", "したくない",
)

# ③ 検索意図カテゴリ — 同一主語でも意図が異なれば別クラスター確定
_INTENT_CATEGORIES: dict[str, frozenset[str]] = {
    "基礎":  frozenset({"とは", "わかりやすく", "初心者", "入門", "基礎", "基本"}),
    "方法":  frozenset({"方法", "やり方", "仕方", "手順", "手続", "手続き", "始め方", "手法"}),
    "評判":  frozenset({"評判", "口コミ", "レビュー", "体験談", "感想", "評価"}),
    "比較":  frozenset({"比較", "おすすめ", "ランキング", "一覧", "まとめ", "違い", "選び方"}),
    "税務":  frozenset({"税金", "確定申告", "申告", "課税", "納税", "etax", "e-tax",
                        "源泉徴収", "雑所得", "分離課税", "累進課税"}),
    "料金":  frozenset({"料金", "費用", "価格", "月額", "年額", "コスト", "値段",
                        "キャンペーン", "クーポン", "割引", "無料"}),
    "解約":  frozenset({"解約", "退会", "やめ方", "辞め方", "解除", "停止"}),
    "特徴":  frozenset({"メリット", "デメリット", "特徴", "強み", "弱み"}),
    "効果":  frozenset({"効果", "結果", "成果", "実績"}),
    "登録":  frozenset({"入会", "登録", "申し込み", "開設", "作り方"}),
}

# ① 複数サービス横断KW（ブランドをまたいで統合してよい）
_MULTI_SERVICE_MARKERS: frozenset[str] = frozenset({
    "おすすめ", "比較", "ランキング", "一覧", "まとめ",
})


def _extract_intent(keyword: str) -> str | None:
    """検索意図カテゴリを返す。該当なしはNone。"""
    import unicodedata
    tokens = set(unicodedata.normalize("NFKC", keyword).lower().split())
    for intent, markers in _INTENT_CATEGORIES.items():
        if tokens & markers:
            return intent
    return None


def _ascii_brand(keyword: str) -> str | None:
    """先頭の純ASCII英字トークン（3文字以上）= ブランド名候補。該当なしはNone。"""
    import re, unicodedata
    parts = unicodedata.normalize("NFKC", keyword).lower().split()
    if parts and re.fullmatch(r'[a-z]{3,}', parts[0]):
        return parts[0]
    return None


def _kani_jaccard(a: str, b: str) -> float:
    """bigram Jaccard（大文字小文字・記号を正規化）"""
    import re, unicodedata
    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKC", s).lower()
        return re.sub(r'[！-／：-＠【】「」『』（）・\s　]+', ' ', s).strip()
    def bigrams(s: str) -> set[str]:
        return {s[i:i+2] for i in range(len(s) - 1)} if len(s) >= 2 else set(s)
    na, nb = norm(a), norm(b)
    ba, bb = bigrams(na), bigrams(nb)
    if not ba and not bb: return 1.0
    if not ba or not bb:  return 0.0
    return len(ba & bb) / len(ba | bb)


def _kani_shared_tokens(a: str, b: str) -> int:
    """スペース区切りトークンの共有数（2文字以上のトークンのみ）"""
    import unicodedata
    def tokens(s: str) -> set[str]:
        return {t for t in unicodedata.normalize("NFKC", s).lower().split() if len(t) >= 2}
    return len(tokens(a) & tokens(b))


def _extract_base_kw(keyword: str) -> str:
    """
    キーワードから主語（ベースKW）を抽出する。

    1. 末尾から修飾語を除去（_BASE_KW_MODIFIERS / _BASE_KW_MODIFIER_SUFFIXES に一致する間）
    2. 残りトークンが 3語以上なら先頭 2語に絞る

    例:
        "ダンボール 買取 相場"  → "ダンボール 買取"
        "転職 初日 注意点"      → "転職 初日"
        "仕事 行きたくない"     → "仕事"
    """
    import unicodedata
    tokens = unicodedata.normalize("NFKC", keyword).lower().split()
    if not tokens:
        return keyword.lower()

    while len(tokens) > 1:
        tail = tokens[-1]
        if tail in _BASE_KW_MODIFIERS:
            tokens.pop()
        elif any(tail.endswith(suf) for suf in _BASE_KW_MODIFIER_SUFFIXES):
            tokens.pop()
        else:
            break

    if len(tokens) >= 3:
        tokens = tokens[:2]

    return " ".join(tokens)


def _cluster_keywords_intra(kws: list[dict]) -> list[dict]:
    """
    グリーディークラスタリングで 親KW / サブKW を決定する。

    volume 降順にソートし、未割り当てのキーワードを順に 親KW として確定。
    判定ルール（上から優先）:
      ③ 検索意図（とは/方法/評判/比較/税務）が双方に存在しかつ異なる → 統合しない（別クラスター）
      1. ベースKW完全一致
      2. ベースKW部分一致（どちらかが他方を含む）
      3/4. bigram Jaccard >= 0.20 または 共有トークン >= 2語
           ① ブランド競合（異なるASCII英字ブランド）→ 要確認
           ④ 広ジャンル過剰統合（先頭トークン共有のみ・Jaccard < 0.35）→ 要確認
      ② 1語ベースで補助条件なし → 要確認（既存ルール）

    Returns:
        [{"main": dict, "subs": [dict, ...]}, ...]
        各 sub dict に "_cluster_reason" / "_cluster_confidence" キーを付与（ログ用）
    """
    import unicodedata
    sorted_kws = sorted(kws, key=lambda x: -x.get("volume", 0))
    for kw in sorted_kws:
        kw["_base"] = _extract_base_kw(kw["keyword"])

    def kw_tokens(kw: str) -> set[str]:
        return set(unicodedata.normalize("NFKC", kw).lower().split())

    assigned: set[int] = set()
    clusters: list[dict] = []

    for i, main_cand in enumerate(sorted_kws):
        if i in assigned:
            continue
        cluster: dict = {"main": main_cand, "subs": []}
        assigned.add(i)
        main_base          = main_cand["_base"]
        main_base_toks     = main_base.split()
        main_base_is_single = len(main_base_toks) == 1
        main_intent        = _extract_intent(main_cand["keyword"])
        main_brand         = _ascii_brand(main_cand["keyword"])
        main_is_multi      = bool(kw_tokens(main_cand["keyword"]) & _MULTI_SERVICE_MARKERS)

        for j, other in enumerate(sorted_kws):
            if j in assigned:
                continue
            other_base      = other["_base"]
            other_base_toks = other_base.split()
            other_intent    = _extract_intent(other["keyword"])

            # ③ 検索意図が双方に明示されかつ異なる → 別クラスター確定（統合しない）
            if main_intent and other_intent and main_intent != other_intent:
                continue

            sim    = _kani_jaccard(main_cand["keyword"], other["keyword"])
            shared = _kani_shared_tokens(main_cand["keyword"], other["keyword"])
            aux_ok = sim >= INTRA_CLUSTER_THRESHOLD or shared >= 2

            reason:     str | None = None
            confidence: str        = "strong"

            # 1. ベースKW完全一致（最優先）
            if main_base and other_base and main_base == other_base:
                if main_base_is_single and not aux_ok:
                    reason     = f"ベースKW一致({main_base!r}) ※Jaccard={sim:.2f}/共有={shared}語"
                    confidence = "weak"
                else:
                    reason = f"ベースKW一致({main_base!r})"

            # 2. ベースKW部分一致
            elif main_base and other_base and (
                main_base in other_base or other_base in main_base
            ):
                # ⑤ 同一意図 かつ other が main より具体的（ベースKWが拡張されている）→ 別クラスター
                # 例: 「チャレンジタッチ 評判」の下に「チャレンジタッチ 不登校 評判」を吸収しない
                if (main_intent and other_intent
                        and main_intent == other_intent
                        and main_base in other_base
                        and main_base != other_base):
                    continue

                if main_base_is_single and not aux_ok:
                    reason     = f"ベースKW部分一致({main_base!r}↔{other_base!r}) ※Jaccard={sim:.2f}/共有={shared}語"
                    confidence = "weak"
                else:
                    reason = f"ベースKW部分一致({main_base!r}↔{other_base!r})"

            # 3/4. Jaccard / 共有トークン（ベースKW不一致 → 追加ガード適用）
            elif sim >= INTRA_CLUSTER_THRESHOLD or shared >= 2:
                other_brand    = _ascii_brand(other["keyword"])
                other_is_multi = bool(kw_tokens(other["keyword"]) & _MULTI_SERVICE_MARKERS)

                if (main_brand and other_brand
                        and main_brand != other_brand
                        and main_brand not in other_brand   # zozo / zozotown は同一
                        and other_brand not in main_brand
                        and not main_is_multi and not other_is_multi):
                    # ① ブランド競合：異なるASCIIブランドはJaccardだけでは統合しない
                    reason     = f"ブランド競合({main_brand!r}≠{other_brand!r}) Jaccard={sim:.2f}"
                    confidence = "weak"

                elif (len(main_base_toks) >= 2 and len(other_base_toks) >= 2
                        and main_base_toks[0] == other_base_toks[0]
                        and main_base != other_base
                        and sim < 0.35):
                    # ④ 広ジャンル過剰統合：先頭トークン共有のみでJaccard < 0.35
                    reason     = f"広ジャンル({main_base_toks[0]!r}系) ベースKW相違 Jaccard={sim:.2f}"
                    confidence = "weak"

                elif sim >= INTRA_CLUSTER_THRESHOLD:
                    reason = f"Jaccard={sim:.2f}"
                else:
                    reason = f"共有トークン={shared}語"

            if reason is not None:
                cluster["subs"].append({
                    **other,
                    "_cluster_reason":     reason,
                    "_cluster_confidence": confidence,
                })
                assigned.add(j)

        clusters.append(cluster)

    return clusters


# WP verdict priority (high=skip > togo > review > ok=0)
_WP_VERDICT_RANK: dict[str, int] = {"skip": 3, "togo": 2, "review": 1, "ok": 0}


def _classify_vs_wp(keyword: str, wp_articles: list[dict]) -> dict:
    """
    KW と WP既存記事タイトルを照合し、3段階分類を返す。

    Returns:
        {
          "verdict": "skip" | "togo" | "review" | "ok",
          "score":   float,
          "title":   str,
          "url":     str,
          "post_id": int | str,
          "memo":    str,
        }

    分類基準:
        skip   … ほぼ同一 / 意図一致かつ高類似 → 新規記事不要
        togo   … 意図一致かつ中類似 → 既存記事に追記
        review … 類似するが意図が曖昧 → 人間確認
        ok     … 類似なし → 新規親KW
    """
    import unicodedata
    empty = {"verdict": "ok", "score": 0.0, "title": "", "url": "", "post_id": "", "memo": ""}
    if not wp_articles:
        return empty

    kw_l        = keyword.lower()
    kw_intent   = _extract_intent(keyword)
    kw_brand    = _ascii_brand(keyword)
    kw_base     = _extract_base_kw(keyword)
    kw_is_multi = bool(
        set(unicodedata.normalize("NFKC", keyword).lower().split()) & _MULTI_SERVICE_MARKERS
    )

    best: dict = empty.copy()

    for article in wp_articles:
        title   = article.get("title", "")
        url     = article.get("link",  article.get("url", ""))
        post_id = article.get("id",    "")
        if not title:
            continue

        # ① ブランド競合 → この記事はスキップ（別ブランド = 別記事）
        title_brand = _ascii_brand(title)
        # 複合語タイトルはスペースがないため _ascii_brand がNoneを返す → 先頭ASCIIをフォールバック検出
        if title_brand is None:
            import re as _re_tb
            _tb_m = _re_tb.match(r'^([a-z]{3,})', unicodedata.normalize("NFKC", title).lower())
            if _tb_m:
                title_brand = _tb_m.group(1)
        if (kw_brand and title_brand
                and kw_brand != title_brand
                and kw_brand not in title_brand
                and title_brand not in kw_brand
                and not kw_is_multi):
            continue

        import unicodedata as _ud
        title_nfkc       = _ud.normalize("NFKC", title).lower()
        kw_nfkc          = _ud.normalize("NFKC", keyword).lower()
        kw_base_compact  = kw_base.replace(" ", "")
        sim    = _kani_jaccard(keyword, title)
        shared = _kani_shared_tokens(keyword, title)

        # ── スコアブースト（日本語WPタイトルはスペースなし複合語が多い）──
        # KW文字列がタイトルに完全含まれる → ほぼ同一
        if kw_l in title_nfkc:
            sim = max(sim, 0.92)
        else:
            # トークン単位の含有チェック（スペース区切りKW ↔ 連結タイトル）
            kw_toks  = {t for t in kw_nfkc.split() if len(t) >= 2}
            if kw_toks:
                n_match = sum(1 for t in kw_toks if t in title_nfkc)
                ratio   = n_match / len(kw_toks)
                if ratio == 1.0:   sim = max(sim, 0.75)   # 全トークン一致
                elif ratio >= 0.8: sim = max(sim, 0.60)   # 80%+
                elif ratio >= 0.5: sim = max(sim, 0.35)   # 50%+
            # ベースKW連結形がタイトルに含まれる（2文字以上）
            if len(kw_base_compact) >= 2 and kw_base_compact in title_nfkc:
                sim = max(sim, 0.55)
            # 「の」「・」除去後の連結形チェック（"買取の相場" など助詞を挟む場合）
            _title_stripped = title_nfkc.replace("の", "").replace("・", "")
            if len(kw_base_compact) >= 2 and kw_base_compact in _title_stripped:
                sim = max(sim, 0.55)

        # ── 意図・ベースKW・ブランドを評価 ──
        title_intent = _extract_intent(title)
        title_base   = _extract_base_kw(title)
        title_base_compact = title_base.replace(" ", "")
        intent_conflict = bool(kw_intent and title_intent and kw_intent != title_intent)
        _title_s = title_nfkc.replace("の", "").replace("・", "")
        base_match = bool(kw_base and (
            kw_base == title_base
            or kw_base in title_base
            or title_base in kw_base
            or (len(kw_base_compact) >= 2 and kw_base_compact in title_nfkc)
            or (len(kw_base_compact) >= 2 and kw_base_compact in _title_s)
            or (len(title_base_compact) >= 2 and title_base_compact in kw_nfkc)
        ))
        # 同ブランドがタイトルに含まれるか（例: "zozo" が "zozo買取サービス..." に含まれる）
        same_brand = bool(
            kw_brand and (title_nfkc.startswith(kw_brand) or f" {kw_brand}" in title_nfkc)
        )
        # KW意図マーカーを除いたコンテンツトークン（例: "副業 おすすめ" → {"副業"}）
        _all_intent_markers: frozenset[str] = frozenset(
            m for ms in _INTENT_CATEGORIES.values() for m in ms
        )
        kw_content_toks = {
            t for t in kw_nfkc.split()
            if len(t) >= 2 and t not in _all_intent_markers
        }
        # KWのコンテンツトークンがタイトルに1つでも含まれるか
        _has_content_overlap = bool(
            kw_content_toks and any(t in title_nfkc for t in kw_content_toks)
        )

        # ── 3段階分類 ──
        # skip: ほぼ同一 or 構造一致+高類似+意図一致
        if sim >= 0.92:
            verdict = "skip"
            memo    = f"WP「{title[:28]}」とほぼ同一(s={sim:.2f})"
        elif sim >= 0.75 and base_match and not intent_conflict:
            verdict = "skip"
            memo    = f"WP「{title[:28]}」とほぼ同一・意図一致(s={sim:.2f})"
        elif sim >= 0.60 and not intent_conflict and base_match:
            verdict = "skip"
            memo    = f"WP「{title[:28]}」と高類似・意図一致(s={sim:.2f})"
        # togo: 関連記事（追記で対応）
        elif sim >= 0.60 and not intent_conflict:
            verdict = "togo"
            memo    = f"WP「{title[:28]}」と関連・追記候補(s={sim:.2f})"
        elif sim >= 0.45 and not intent_conflict and (base_match or shared >= 2 or same_brand):
            # KW意図が明示されているが記事タイトルが複合語で意図不明 → 保守的に要確認
            if kw_intent and title_intent is None and (base_match or shared >= 2) and not same_brand:
                verdict = "review"
                memo    = f"WP「{title[:28]}」と意図不明→要確認(s={sim:.2f})"
            else:
                verdict = "togo"
                memo    = f"WP「{title[:28]}」と検索意図近似→追記候補(s={sim:.2f})"
        # 同ブランド記事・意図非競合 → 追記候補（低閾値）
        elif sim >= 0.30 and not intent_conflict and same_brand:
            verdict = "togo"
            memo    = f"WP「{title[:28]}」と同ブランド関連→追記候補(s={sim:.2f})"
        # review: 類似するが意図が曖昧 / KW意図明示+コンテンツ一致
        elif sim >= 0.20 and (intent_conflict or base_match or same_brand
                              or (kw_intent and sim >= 0.25 and _has_content_overlap)):
            verdict = "review"
            memo    = (
                f"WP「{title[:28]}」と意図が異なる可能性(s={sim:.2f})" if intent_conflict
                else f"WP「{title[:28]}」と部分類似→要確認(s={sim:.2f})"
            )
        else:
            continue  # 閾値以下は無視

        # より高い verdict またはスコアで更新
        if (_WP_VERDICT_RANK[verdict] > _WP_VERDICT_RANK[best["verdict"]]
                or (verdict == best["verdict"] and sim > best["score"])):
            best = {
                "verdict":  verdict,
                "score":    sim,
                "title":    title,
                "url":      url,
                "post_id":  post_id,
                "memo":     memo,
            }

    return best


def run_kanikabari_check(blog_cfg: BlogConfig) -> None:
    """
    シートの未判定AIMキーワードに対してかにばりチェックを実行し、結果を書き込む。

    Step 1: シートから 判定列が空の AIM="aim" キーワードを取得
    Step 2: キーワード間クラスタリング（intra-sheet）→ 親KW / サブKW 決定
    Step 3: 親KWについて WP既存記事との重複チェック
    Step 4: シートに書き込む（D=判定, E=統合先KW, G=ステータス, H=メモ）
    """
    import gspread
    from google.oauth2.service_account import Credentials

    ss_id = blog_cfg.candidate_ss_id
    sheet = blog_cfg.candidate_sheet

    log.info(f"[kanikabari] 開始: {blog_cfg.display_name} / シート「{sheet}」")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc    = gspread.authorize(creds)
    ws    = gc.open_by_key(ss_id).worksheet(sheet)

    rows   = ws.get_all_values()
    header = rows[0] if rows else []

    def col(names: list[str]) -> int:
        for name in names:
            if name in header:
                return header.index(name)
        return -1

    kw_idx     = col(["キーワード", "Keyword"])
    vol_idx    = col(["月間検索数", "検索ボリューム", "volume"])
    aim_idx    = col(["aim", "AIM", "Aim"])
    hantei_idx = col(["判定"])

    if hantei_idx < 0:
        log.error("[kanikabari] 「判定」列が見つかりません。新フォーマットのシートか確認してください。")
        return
    if kw_idx < 0:
        log.error("[kanikabari] 「キーワード」列が見つかりません。")
        return

    def to_int(v: str) -> int:
        if not v or v.upper() in ("N/A", "NULL", "-", ""):
            return 0
        try:
            return int(float(v))
        except ValueError:
            return 0

    # 未判定の AIM キーワードを収集（1-based 行番号付き）
    unjudged: list[dict] = []
    for row_idx, row in enumerate(rows[1:], start=2):
        def cell(i: int, _row: list = row) -> str:
            return _row[i].strip() if 0 <= i < len(_row) else ""

        kw     = cell(kw_idx)
        aim    = cell(aim_idx).lower() if aim_idx >= 0 else ""
        hantei = cell(hantei_idx)

        if not kw:
            continue
        if aim not in ("aim", "claude", "add"):
            continue
        if hantei:  # 既に判定済みはスキップ
            continue

        unjudged.append({
            "keyword": kw,
            "volume":  to_int(cell(vol_idx)),
            "_row":    row_idx,
        })

    log.info(f"[kanikabari] 未判定AIMキーワード: {len(unjudged)}件")
    if not unjudged:
        log.info("[kanikabari] 処理対象なし。終了します。")
        return

    # intra-sheet クラスタリング
    clusters = _cluster_keywords_intra(unjudged)
    log.info(f"[kanikabari] クラスタリング結果: {len(clusters)}クラスター")
    for c in clusters:
        main_base = c["main"].get("_base", "")
        if c["subs"]:
            subs_str = "  ".join(
                "[要確認] " * (s.get("_cluster_confidence") == "weak")
                + f"「{s['keyword']}」({s.get('_cluster_reason', '')})"
                for s in c["subs"]
            )
            log.info(f"  親KW: 「{c['main']['keyword']}」[base={main_base!r}]  サブKW: {subs_str}")
        else:
            log.info(f"  親KW: 「{c['main']['keyword']}」[base={main_base!r}]  (サブKWなし)")

    # ── Step 1: WP既存記事を取得（全ステータス）────────────────────────
    wp_articles: list[dict] = []
    try:
        wp_articles = fetch_wp_posts(blog_cfg=blog_cfg)
        pub   = sum(1 for p in wp_articles if p["status"] == "publish")
        draft = sum(1 for p in wp_articles if p["status"] == "draft")
        log.info(f"[kanikabari] WP既存記事: {len(wp_articles)}件取得 (公開={pub} / 下書き={draft})")
    except Exception as e:
        log.warning(f"[kanikabari] WP記事取得失敗（WPチェックなしで続行）: {e}")

    # ── Step 2: 最終結果をまとめる ──────────────────────────────────
    results: list[dict] = []

    def _sub_result(sub: dict, togo_ref: str, wp_url: str = "", wp_id: str = "") -> dict:
        """サブKW1件分の result dict を生成するヘルパー。"""
        if sub.get("_cluster_confidence") == "weak":
            return {
                "keyword":   sub["keyword"],
                "row":       sub["_row"],
                "hantei":    "要確認",
                "togo_saki": "",
                "status":    "要確認",
                "memo":      sub.get("_cluster_reason", ""),
                "wp_url":    wp_url,
                "wp_id":     wp_id,
            }
        return {
            "keyword":   sub["keyword"],
            "row":       sub["_row"],
            "hantei":    "サブKW",
            "togo_saki": togo_ref,
            "status":    "統合対象",
            "memo":      "",
            "wp_url":    wp_url,
            "wp_id":     wp_id,
        }

    for cluster in clusters:
        main_kw = cluster["main"]
        wp      = _classify_vs_wp(main_kw["keyword"], wp_articles)

        if wp["verdict"] == "skip":
            # ── カニバリスキップ ─────────────────────────────────────
            results.append({
                "keyword":   main_kw["keyword"],
                "row":       main_kw["_row"],
                "hantei":    "カニバリスキップ",
                "togo_saki": wp["title"],
                "status":    "カニバリスキップ",
                "memo":      wp["memo"],
                "wp_url":    wp["url"],
                "wp_id":     str(wp["post_id"]),
            })
            # サブKWは引き続きその WP 記事への統合対象とする
            for sub in cluster["subs"]:
                results.append(_sub_result(sub, wp["title"], wp["url"], str(wp["post_id"])))

        elif wp["verdict"] == "togo":
            # ── 統合対象（既存WP記事への追記候補）──────────────────────
            results.append({
                "keyword":   main_kw["keyword"],
                "row":       main_kw["_row"],
                "hantei":    "サブKW",
                "togo_saki": wp["title"],
                "status":    "統合対象",
                "memo":      wp["memo"],
                "wp_url":    wp["url"],
                "wp_id":     str(wp["post_id"]),
            })
            for sub in cluster["subs"]:
                results.append(_sub_result(sub, wp["title"], wp["url"], str(wp["post_id"])))

        elif wp["verdict"] == "review":
            # ── 要確認（既存WP記事との関係が曖昧）──────────────────────
            results.append({
                "keyword":   main_kw["keyword"],
                "row":       main_kw["_row"],
                "hantei":    "要確認",
                "togo_saki": "",
                "status":    "要確認",
                "memo":      wp["memo"],
                "wp_url":    wp["url"],
                "wp_id":     str(wp["post_id"]),
            })
            for sub in cluster["subs"]:
                results.append(_sub_result(sub, main_kw["keyword"]))

        else:
            # ── ok → 新規親KW（生成待ち）────────────────────────────
            results.append({
                "keyword":   main_kw["keyword"],
                "row":       main_kw["_row"],
                "hantei":    "親KW",
                "togo_saki": "",
                "status":    "生成待ち",
                "memo":      "",
                "wp_url":    "",
                "wp_id":     "",
            })
            for sub in cluster["subs"]:
                results.append(_sub_result(sub, main_kw["keyword"]))

    log.info(f"[kanikabari] 書き込み対象: {len(results)}件")

    from modules.sheets_updater import mark_kanikabari_results_new_format
    mark_kanikabari_results_new_format(results, ws)

    n_ok    = sum(1 for r in results if r["hantei"] == "親KW" and r["status"] == "生成待ち")
    n_togo  = sum(1 for r in results if r["status"] == "統合対象" and r["wp_id"])
    n_skip  = sum(1 for r in results if r["status"] == "カニバリスキップ")
    n_sub   = sum(1 for r in results if r["hantei"] == "サブKW" and not r["wp_id"])
    n_rev   = sum(1 for r in results if r["status"] == "要確認")
    log.info(
        f"[kanikabari] 完了: 親KW生成待ち={n_ok}件 / シート内サブKW={n_sub}件"
        f" / WP統合対象={n_togo}件 / カニバリスキップ={n_skip}件 / 要確認={n_rev}件"
    )

    # 代表的な判定例をログ出力
    examples = (
        [r for r in results if r["status"] == "カニバリスキップ"][:2]
        + [r for r in results if r["status"] == "統合対象" and r["wp_id"]][:2]
        + [r for r in results if r["status"] == "要確認" and r["wp_id"]][:2]
    )
    for ex in examples:
        log.info(
            f"  [{ex['hantei']}] 「{ex['keyword']}」→ {ex['status']}"
            + (f" / WP「{ex['togo_saki'][:25]}」" if ex.get("togo_saki") else "")
        )


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(description="軽量版記事生成システム (マルチブログ対応)")
    parser.add_argument("--site",     default="workup-ai",
                        help="対象サイト（後方互換用。--blogs 未指定時のデフォルトブログ名）")
    parser.add_argument("--blogs",    nargs="*", metavar="BLOG",
                        help="実行するブログ名（省略時は blogs/ ディレクトリ内を全件実行）")
    parser.add_argument("--blog",     metavar="BLOG",
                        help="ブログを番号または名前で指定（例: 1, aivice, AIVICE）")
    parser.add_argument("--count",    type=int, default=None,
                        help="生成記事数（省略時は各ブログの blog_config.json に従う）")
    parser.add_argument("--keyword",  help="キーワードを直接指定（1ブログ・1件のみ対応）")
    parser.add_argument("--title",    help="記事タイトルを強制指定（--keyword と併用）")
    parser.add_argument("--volume",   type=int, default=0, help="--keyword 指定時の月間検索数")
    parser.add_argument("--dry-run",  action="store_true", help="WP投稿をスキップ")
    parser.add_argument("--yes", "-y", action="store_true", help="実行前確認をスキップ")
    parser.add_argument("--test",     action="store_true",
                        help="テスト生成モード: 1記事のみ生成・下書き保存（--count 1 と同等）")
    parser.add_argument("--kanikabari", action="store_true",
                        help="かにばりチェックを実行してシートに判定を書き込む（記事生成はしない）")
    args = parser.parse_args()

    # --test フラグ: count=1 を強制（--count と同時指定時は --count を優先）
    if args.test and args.count is None:
        args.count = 1
        log.info("[test] テストモード: 1記事生成")

    started_at = datetime.now()
    log.info("=" * 60)
    log.info(f"generate_lite.py 開始  dry_run={args.dry_run}")
    log.info("=" * 60)

    # ── ブログ一覧の決定 ──────────────────────────────────
    registry_map: dict[str, dict] = {}  # name -> registry entry（guide_links 等）

    if args.blog is not None:
        # --blog: 番号または名前で1ブログ指定
        blog_names = [resolve_blog(args.blog)]
    elif FEATURES["multi_blog"]:
        if args.blogs is not None:
            blog_names = args.blogs  # --blogs で明示指定
        else:
            # ブログ管理シートから稼働中ブログを動的取得（フォールバック: ローカルディレクトリ）
            try:
                from modules.blog_registry import load_active_blogs
                registry_entries = load_active_blogs(GOOGLE_CREDENTIALS_PATH)
                if registry_entries:
                    blog_names  = [e["name"] for e in registry_entries]
                    registry_map = {e["name"]: e for e in registry_entries}
                    log.info(f"[registry] ブログ管理シートから {len(blog_names)} 件取得: {blog_names}")
                else:
                    log.warning("[registry] シートから稼働中ブログが0件 → ローカルディレクトリにフォールバック")
                    blog_names = list_blogs()
            except Exception as _reg_err:
                log.warning(f"[registry] ブログ管理シート読み込みエラー → フォールバック: {_reg_err}")
                blog_names = list_blogs()

            if not blog_names:
                # blogs/ が空の場合は --site をフォールバックとして使用
                blog_names = [args.site]
    else:
        blog_names = [args.site]

    if not blog_names:
        log.error("実行対象ブログが0件です。blogs/ ディレクトリを確認してください。")
        sys.exit(1)

    log.info(f"対象ブログ: {blog_names}")

    # ── ブログごとに順次実行 ──────────────────────────────
    all_results: list[dict] = []
    for blog_name in blog_names:
        try:
            blog_cfg = load_blog_config(blog_name)
        except FileNotFoundError as e:
            log.error(f"[{blog_name}] 設定ファイルが見つかりません（スキップ）: {e}")
            continue

        # ── ブログ管理シートの guide_links でローカル設定を上書き ──
        if registry_map.get(blog_name):
            sheet_guide = registry_map[blog_name].get("guide_links", {})
            if any(v.strip() for v in sheet_guide.values() if v):
                blog_cfg.guide_links = {k: v for k, v in sheet_guide.items() if v.strip()}
                log.debug(f"[{blog_name}] シートの guide_links を適用: {blog_cfg.guide_links}")

        domain = blog_cfg.wp_url.replace("https://", "").replace("http://", "").rstrip("/")
        log.info(f"\n{'═' * 60}")
        log.info(f"=== {blog_cfg.display_name} ({domain}) 処理開始 ===")
        log.info(f"{'═' * 60}")

        # ── 実行前確認（--yes または非TTYのときはスキップ）──
        if not confirm_blog(blog_cfg, skip=args.yes):
            log.info(f"[{blog_name}] キャンセルされました。")
            continue

        if args.kanikabari:
            run_kanikabari_check(blog_cfg)
        else:
            results = run_blog(
                blog_cfg,
                dry_run=args.dry_run,
                keyword=args.keyword,
                volume=args.volume,
                count=args.count,
                forced_title=args.title,
            )
            all_results.extend(results)

    # ── 全体サマリー ──────────────────────────────────────
    elapsed   = (datetime.now() - started_at).total_seconds()
    n_success = sum(1 for r in all_results if r["status"] in ("success", "dry-run"))
    n_error   = sum(1 for r in all_results if r["status"] == "error")

    log.info(f"\n{'=' * 60}")
    log.info("【全体サマリー】")
    log.info(f"  ブログ数  : {len(blog_names)}件")
    log.info(f"  生成件数  : {n_success}件成功 / {n_error}件失敗 / 計{len(all_results)}件")
    log.info(f"  所要時間  : {elapsed:.1f}秒")
    for r in all_results:
        status_icon = "✅" if r["status"] in ("success", "dry-run") else "❌"
        title = r.get("title", "(生成失敗)")
        url   = r.get("edit_url", "")
        blog  = r.get("blog", "?")
        log.info(f"  {status_icon} [{blog}] {r['keyword']} → {title}")
        if url:
            log.info(f"       {url}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
