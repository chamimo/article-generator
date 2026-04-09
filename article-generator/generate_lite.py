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

# ═══════════════════════════════════════════════════════════════
# FEATURE FLAGS
# Phase 2以降で True に切り替える。既存ロジックには影響しない。
# ═══════════════════════════════════════════════════════════════
FEATURES: dict[str, bool] = {
    "trend_from_x":     False,  # (未使用) X API連携 → fetch_trend_keywords() に置換
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
TITLE_SIM_THRESHOLD = 0.75 # タイトル類似度閾値（Jaccard bigram）
BLOGS_DIR         = Path(__file__).parent / "blogs"

# Phase 2: 記事タイプ配分（article_type_mix=True 時に使用）
ARTICLE_TYPE_WEIGHTS: dict[str, float] = {
    "longtail": 0.5,   # ロングテール記事（安定流入）
    "trend":    0.3,   # トレンド記事（短期流入）
    "monetize": 0.2,   # 収益化記事（CV重視）
}


# ═══════════════════════════════════════════════════════════════
# ARTICLE TYPE
# Phase 2で記事生成ロジックの分岐に使用
# ═══════════════════════════════════════════════════════════════
class ArticleType(Enum):
    LONGTAIL = "longtail"   # ロングテール：SEO安定流入狙い
    TREND    = "trend"      # トレンド：時事・季節性キーワード（Phase 2）
    MONETIZE = "monetize"   # 収益化：CVR高いキーワード（Phase 2）


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
    target_length:    int
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
    asp_links: dict = field(default_factory=dict)       # ASP案件リンク {名称: URL}
    # 追加設定はここに列追加するだけで OK
    extra: dict = field(default_factory=dict)


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

    return BlogConfig(
        name            = blog_name,
        display_name    = data.get("display_name", blog_name),
        genre           = data.get("genre", ""),
        target_length   = int(data.get("target_length", 3000)),
        fact_check      = bool(data.get("fact_check", True)),
        candidate_ss_id = data.get("candidate_ss_id", CANDIDATE_SS_ID),
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
        asp_links       = {str(k): str(v) for k, v in data.get("asp_links", {}).items()},
        extra           = {k: v for k, v in data.items()
                           if k not in ("name", "display_name", "genre", "target_length",
                                        "fact_check", "candidate_ss_id", "candidate_sheet",
                                        "article_count", "min_volume", "wp_url", "wp_username",
                                        "wp_app_password", "article_type_weights",
                                        "stop_words", "aliases", "allowed_themes",
                                        "ng_keywords", "asp_links", "_comment")
                           and not k.endswith("_env")},
    )


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


def confirm_blog(blog_cfg: "BlogConfig") -> bool:
    """
    実行前の確認プロンプトを表示し、y なら True を返す。
    stdin が TTY でない場合（cron等）は自動的に True を返す。
    """
    if not sys.stdin.isatty():
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

    kw_idx   = col(["キーワード", "Keyword"])
    vol_idx  = col(["月間検索数", "検索ボリューム", "volume"])
    seo_idx  = col(["SEO難易度", "seo_difficulty"])
    comp_idx = col(["競合性", "competition"])
    aim_idx  = col(["aim", "AIM", "Aim"])

    # aim列の値 → 優先度レベル（高いほど先に評価）
    _AIM_PRIORITY = {"now": 4, "future": 3, "monetize": 2, "aim": 1, "add": 1}

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

    for row in rows[1:]:
        def cell(i: int) -> str:
            return row[i].strip() if 0 <= i < len(row) else ""

        kw   = cell(kw_idx)
        vol_raw = cell(vol_idx)
        vol  = to_int(vol_raw)      # None = N/A
        seo  = to_int(cell(seo_idx))
        comp = to_int(cell(comp_idx))
        aim  = cell(aim_idx).lower().strip() if aim_idx >= 0 else ""

        if not kw:
            continue

        # vol=N/A（None）はメイン扱い、明示的な数値は30以上のみメイン
        is_main = (vol is None) or (vol >= MAIN_VOL_THRESHOLD)
        vol_int = vol if vol is not None else 0

        if not is_main:
            # vol<30 → サブKWとして収集（min_vol チェック不要）
            sub_keywords.append(kw)
            continue

        if vol_int < min_vol:
            continue

        candidates.append({
            "keyword":         kw,
            "volume":          vol_int,
            "seo_difficulty":  seo,
            "competition":     comp,
            "priority":        aim == "now",                    # 後方互換
            "_aim":            aim,                              # aim列の生値
            "_priority_level": _AIM_PRIORITY.get(aim, 0),      # 優先度スコア
        })

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
        # NGワードチェック（ブラックリスト）
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
        f"  サブKW: {len(sub_keywords)}件（vol<{MAIN_VOL_THRESHOLD}）"
        + (f"  テーマ外除外: {filtered_out}件" if filtered_out else "")
        + (f"  aim内訳: [{aim_summary}]" if aim_summary else "")
    )
    return candidates, sub_keywords


# ═══════════════════════════════════════════════════════════════
# STEP 1.5: WP公開記事取得 & 重複チェック
# ═══════════════════════════════════════════════════════════════
def fetch_wp_posts(blog_cfg: BlogConfig | None = None) -> list[dict]:
    """
    WordPress REST API で公開済み記事を全件取得する。
    blog_cfg が指定された場合はそのブログの WP 認証情報を使用する。

    Returns:
        [{"id": int, "title": str, "slug": str, "date": str}, ...]
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
        "status":   "publish",
        "_fields":  "id,title,date,slug",
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
                "id":    p.get("id"),
                "title": title,
                "slug":  p.get("slug", ""),
                "date":  p.get("date", ""),
            })
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        if params["page"] >= total_pages:
            break
        params["page"] += 1

    log.info(f"[wp] 公開済み記事取得: {len(all_posts)}件")
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

    recent_posts = []
    for p in wp_posts:
        title_raw  = p["title"]
        slug       = p["slug"].replace("-", " ")
        norm_title = _normalize_title(title_raw)

        # (0) コアKW重複（最優先）─ ストップワード除去後のコア一致
        if _stop and core_valid:
            core_title = _extract_core_keyword(title_raw, _stop)
            # 候補のコアが既存記事タイトルに含まれる、または逆方向
            if (core_kw in core_title
                    or (len(core_title.replace(" ", "")) >= 4 and core_title in core_kw)):
                return True, f"コアKW重複: 「{title_raw[:40]}」(core: {core_kw!r})"

        # (1) 同一キーワード
        if kw_lower in title_raw.lower() or kw_lower in slug:
            return True, f"同一キーワード: 「{title_raw[:40]}」"

        # (2) 同一タイトル（正規化後）
        if norm_kw and norm_title and norm_kw == norm_title:
            return True, f"同一タイトル: 「{title_raw[:40]}」"

        # (3) 近似タイトル
        sim = _title_similarity(norm_kw, norm_title)
        if sim >= TITLE_SIM_THRESHOLD:
            return True, f"近似タイトル({sim:.2f}): 「{title_raw[:40]}」"

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
# 既存の generate_article() をそのまま利用
# ═══════════════════════════════════════════════════════════════
def generate(
    keyword: str,
    volume: int,
    blog_cfg: BlogConfig | None = None,
    sub_keywords: list[str] | None = None,
) -> dict:
    """
    記事を生成して dict で返す。
    blog_cfg が指定された場合はそのブログの設定（fact_check）を反映する。
    sub_keywords が指定された場合は記事本文に自然に盛り込む。
    """
    fact_check = blog_cfg.fact_check if blog_cfg is not None else True
    log.info(
        f"[generate] 生成開始: 「{keyword}」(vol:{volume:,}) fact_check={fact_check}"
        + (f"  サブKW:{len(sub_keywords)}件" if sub_keywords else "")
    )
    article = generate_article(keyword, volume, sub_keywords=sub_keywords,
                               enable_fact_check=fact_check)
    log.info(f"[generate] 完了: 「{article['title']}」")
    return article


# ═══════════════════════════════════════════════════════════════
# STEP 4: WordPress投稿
# Phase 2: 画像生成・CTA挿入・シートフラグ更新を追加予定
# ═══════════════════════════════════════════════════════════════
def post(article: dict, dry_run: bool = False,
         blog_cfg: BlogConfig | None = None) -> dict:
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

    if FEATURES["image_generation"]:
        # 画像生成 → post_article_with_image（アイキャッチ設定・H2画像注入を含む）
        image_bytes: bytes | None = None
        keyword = article.get("keyword", "")
        try:
            image_bytes = generate_image_for_article(keyword=keyword)
            log.info(f"[post] 画像生成完了: {len(image_bytes):,} bytes")
        except Exception as img_err:
            log.warning(f"[post] 画像生成スキップ（続行）: {img_err}")

        asp_links = blog_cfg.asp_links if blog_cfg else {}
        result = post_article_with_image(article, image_bytes=image_bytes,
                                         asp_links=asp_links)
    else:
        result = create_post(article, featured_media_id=None)

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

    # ── Step 1: キーワード選定 ──────────────────────────
    sub_keywords: list[str] = []  # vol<30のサブKW（記事本文に盛り込む）
    if keyword:
        targets = [{"keyword": keyword, "volume": volume,
                    "seo_difficulty": None, "competition": None,
                    "priority": False, "_type": "longtail", "_aim": ""}]
        log.info(f"[{blog_cfg.name}] キーワード直接指定: 「{keyword}」")
        n_candidates = 1
    else:
        # WP公開記事取得（ブログ単位の重複チェック・全タイプ共通）
        wp_posts: list[dict] | None = None
        if FEATURES["duplicate_check"]:
            try:
                wp_posts = fetch_wp_posts(blog_cfg=blog_cfg)
            except Exception as e:
                log.warning(f"[{blog_cfg.name}] WP記事取得失敗（重複チェックなしで続行）: {e}")

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
            # メインKWに関連するサブKWを抽出して記事本文に盛り込む
            kw_core = _extract_core_keyword(chosen["keyword"].lower(), stop_words)
            related_sub = [
                s for s in sub_keywords
                if kw_core and kw_core in s.lower()
            ][:20]  # 最大20件まで渡す

            article     = generate(chosen["keyword"], chosen["volume"],
                                   blog_cfg=blog_cfg, sub_keywords=related_sub or None)
            post_result = post(article, dry_run=dry_run, blog_cfg=blog_cfg)

            item.update({
                "status":      post_result["status"],
                "title":       article["title"],
                "post_id":     post_result.get("id"),
                "edit_url":    post_result.get("edit_url", ""),
                "finished_at": datetime.now().isoformat(),
            })
            n_success += 1
            log.info(f"[{blog_cfg.name}] [{i}/{len(targets)}] ✅ 完了: 「{article['title']}」")

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
        f"[{blog_cfg.name}] 完了: 成功={n_success}件 / 失敗={n_error}件 / 合計={len(targets)}件"
    )
    return results


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
    parser.add_argument("--volume",   type=int, default=0, help="--keyword 指定時の月間検索数")
    parser.add_argument("--dry-run",  action="store_true", help="WP投稿をスキップ")
    parser.add_argument("--yes", "-y", action="store_true", help="実行前確認をスキップ")
    args = parser.parse_args()

    started_at = datetime.now()
    log.info("=" * 60)
    log.info(f"generate_lite.py 開始  dry_run={args.dry_run}")
    log.info("=" * 60)

    # ── ブログ一覧の決定 ──────────────────────────────────
    if args.blog is not None:
        # --blog: 番号または名前で1ブログ指定
        blog_names = [resolve_blog(args.blog)]
    elif FEATURES["multi_blog"]:
        if args.blogs is not None:
            blog_names = args.blogs  # --blogs で明示指定
        else:
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

        domain = blog_cfg.wp_url.replace("https://", "").replace("http://", "").rstrip("/")
        log.info(f"\n{'═' * 60}")
        log.info(f"=== {blog_cfg.display_name} ({domain}) 処理開始 ===")
        log.info(f"{'═' * 60}")

        # ── 実行前確認（--blog 指定時のみ、TTY かつ --yes なし）──
        if args.blog is not None and not args.yes:
            if not confirm_blog(blog_cfg):
                log.info(f"[{blog_name}] キャンセルされました。")
                continue

        results = run_blog(
            blog_cfg,
            dry_run=args.dry_run,
            keyword=args.keyword,
            volume=args.volume,
            count=args.count,
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
