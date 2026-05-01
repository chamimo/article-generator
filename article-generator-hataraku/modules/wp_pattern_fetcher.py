"""
wp_pattern_fetcher.py

WordPress の「マイパターン」（/wp-json/wp/v2/blocks）を取得し、
記事末尾の CTA 位置にパターン HTML を挿入するユーティリティ。

主な関数:
    fetch_patterns(blog_cfg)            -> list[PatternItem]
    match_pattern(keyword, patterns)    -> PatternItem | None
    insert_pattern_cta(html, pattern)   -> str
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class PatternItem:
    id:      int
    title:   str
    html:    str
    # タイトルを正規化したトークンセット（マッチング用）
    tokens:  frozenset[str] = field(default_factory=frozenset, repr=False)

    def __post_init__(self) -> None:
        if not self.tokens:
            self.tokens = _tokenize(self.title)


# ──────────────────────────────────────────────────────────
# 内部ユーティリティ
# ──────────────────────────────────────────────────────────

def _tokenize(text: str) -> frozenset[str]:
    """NFKC正規化→小文字→スペース分割 で2文字以上のトークンを返す。"""
    normalized = unicodedata.normalize("NFKC", text).lower()
    return frozenset(t for t in re.split(r"[\s\-_・/【】「」]+", normalized) if len(t) >= 2)


def _render(field_val: object) -> str:
    """WP REST API の {"rendered": "..."} / {"raw": "..."} 形式または文字列を返す。
    ブロック API は rendered なしで raw のみ返すことがある。"""
    if isinstance(field_val, dict):
        return field_val.get("rendered") or field_val.get("raw", "")
    return str(field_val) if field_val else ""


# ──────────────────────────────────────────────────────────
# パターン取得
# ──────────────────────────────────────────────────────────

def fetch_patterns(blog_cfg) -> list[PatternItem]:
    """
    WP REST API /wp-json/wp/v2/blocks からマイパターン一覧を取得する。

    - パターンが存在しない・エンドポイントが 404 の場合は空リストを返す（エラーにしない）
    - blog_cfg は generate_lite.BlogConfig（wp_url / wp_username / wp_app_password を持つ）

    Returns:
        list[PatternItem]  -- 取得件数0件の場合は空リスト
    """
    import requests
    from requests.auth import HTTPBasicAuth

    wp_url  = getattr(blog_cfg, "wp_url", "").rstrip("/")
    user    = getattr(blog_cfg, "wp_username", "")
    pw      = getattr(blog_cfg, "wp_app_password", "")

    if not wp_url:
        log.warning("[wp_pattern_fetcher] wp_url が未設定のためスキップ")
        return []

    auth     = HTTPBasicAuth(user, pw)
    endpoint = f"{wp_url}/wp-json/wp/v2/blocks"
    params   = {"per_page": 100, "page": 1, "_fields": "id,title,content"}

    patterns: list[PatternItem] = []

    while True:
        try:
            resp = requests.get(endpoint, params=params, auth=auth, timeout=15)
        except Exception as exc:
            log.warning(f"[wp_pattern_fetcher] 接続エラー: {exc}")
            break

        # 404 = ブロックエンドポイント無効 or パターン未使用 → スキップ
        if resp.status_code == 404:
            log.info(f"[wp_pattern_fetcher] {wp_url}: /wp/v2/blocks が存在しません（スキップ）")
            break

        if resp.status_code != 200:
            log.warning(f"[wp_pattern_fetcher] HTTP {resp.status_code} — スキップ")
            break

        batch = resp.json()
        if not batch:
            break

        for item in batch:
            title = _render(item.get("title", ""))
            html  = _render(item.get("content", ""))
            if title:
                patterns.append(PatternItem(id=int(item["id"]), title=title, html=html))

        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        if params["page"] >= total_pages:
            break
        params["page"] += 1

    log.info(f"[wp_pattern_fetcher] {wp_url}: マイパターン {len(patterns)} 件取得")
    return patterns


# ──────────────────────────────────────────────────────────
# キーワードとのマッチング
# ──────────────────────────────────────────────────────────

def match_pattern(keyword: str, patterns: list[PatternItem]) -> PatternItem | None:
    """
    キーワードに最も関連するパターンを返す。

    スコア計算:
        - 完全一致トークン × 2 点
        - サブストリング一致（KWトークンがパターントークンに含まれる、またはその逆）× 1 点
    スコア 0 → None（マッチなし）

    Returns:
        PatternItem | None
    """
    if not patterns:
        return None

    kw_tokens = _tokenize(keyword)
    if not kw_tokens:
        return None

    best: PatternItem | None = None
    best_score = 0

    for pat in patterns:
        # 完全一致（高スコア）
        exact = len(kw_tokens & pat.tokens)
        # サブストリング一致（日本語複合語タイトル対応）
        substr = sum(
            1 for kw_t in kw_tokens for pt_t in pat.tokens
            if kw_t in pt_t or pt_t in kw_t
        )
        score = exact * 2 + substr

        if score > best_score:
            best_score = score
            best = pat

    if best_score == 0:
        return None

    log.debug(
        f"[wp_pattern_fetcher] KW={keyword!r} → パターン「{best.title}」 (score={best_score})"
    )
    return best


# ──────────────────────────────────────────────────────────
# 記事 HTML への CTA 挿入
# ──────────────────────────────────────────────────────────

# CTA を挿入する直前のアンカーパターン（優先順）
_CTA_ANCHORS = [
    r'<!-- /wp:heading -->(?=\s*<!-- wp:paragraph -->)',  # 見出し直後の段落前
    r'(</h[23]>)',                                        # h2/h3 タグ直後
]

# 記事末尾の「まとめ」相当の見出しを探すパターン
_SUMMARY_HEADING = re.compile(
    r'(<!-- wp:heading[^>]*>.*?<h[23][^>]*>(?:まとめ|総まとめ|最後に|おわりに)[^<]*</h[23]>.*?<!-- /wp:heading -->)',
    re.DOTALL | re.IGNORECASE,
)

# フォールバック: 末尾 </p> の直後
_LAST_P = re.compile(r'(</p>\s*)$', re.DOTALL)


def insert_pattern_cta(article_html: str, pattern: PatternItem) -> str:
    """
    記事 HTML の CTA 位置にパターン HTML を挿入して返す。

    挿入位置の優先順:
        1. 「まとめ」系見出しブロックの直前
        2. 末尾の </p> の直後
        3. 上記なし → 末尾に追記

    Returns:
        str  挿入済みの記事 HTML
    """
    if not pattern.html.strip():
        log.debug("[wp_pattern_fetcher] パターン HTML が空のため挿入をスキップ")
        return article_html

    cta_block = (
        f'\n<!-- wp:block {{"ref":{pattern.id}}} /-->\n'
        if not pattern.html.strip().startswith("<!-- wp:")
        else f"\n{pattern.html.strip()}\n"
    )

    # 1. 「まとめ」見出しの直前に挿入
    m = _SUMMARY_HEADING.search(article_html)
    if m:
        pos = m.start()
        log.debug(f"[wp_pattern_fetcher] 「まとめ」見出し直前 (pos={pos}) に挿入")
        return article_html[:pos] + cta_block + article_html[pos:]

    # 2. 末尾 </p> の直後に挿入
    m2 = _LAST_P.search(article_html)
    if m2:
        pos = m2.end()
        log.debug(f"[wp_pattern_fetcher] 末尾 </p> 直後 (pos={pos}) に挿入")
        return article_html[:pos] + cta_block + article_html[pos:]

    # 3. 末尾に追記
    log.debug("[wp_pattern_fetcher] 末尾に追記")
    return article_html + cta_block
