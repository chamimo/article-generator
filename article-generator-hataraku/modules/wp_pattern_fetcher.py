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

# wp:paragraph ブロック全体にマッチ
_WP_PARA_BLOCK = re.compile(
    r'<!-- wp:paragraph[^>]*-->.*?<!-- /wp:paragraph -->',
    re.DOTALL,
)

# SWELL「この記事のポイント」ブロックの閉じタグ
_POINTS_BLOCK_END = re.compile(
    r'<!-- /wp:loos/cap-block -->',
    re.IGNORECASE,
)


def _find_points_block_end(article_html: str) -> int | None:
    """「この記事のポイント」ブロック（wp:loos/cap-block）の終端位置を返す。"""
    m = _POINTS_BLOCK_END.search(article_html)
    return m.end() if m else None


def _find_mention_end(article_html: str, tokens: frozenset[str]) -> int | None:
    """
    パターンのトークンを含む最後の wp:paragraph ブロックの終端位置を返す。
    見つからなければ None。
    """
    search_terms = sorted(
        (t for t in tokens if len(t) >= 2),
        key=len, reverse=True,
    )[:8]
    if not search_terms:
        return None

    mention_end: int | None = None
    for m in _WP_PARA_BLOCK.finditer(article_html):
        block_lower = m.group().lower()
        if any(t in block_lower for t in search_terms):
            mention_end = m.end()

    return mention_end


def insert_pattern_cta(article_html: str, pattern: PatternItem) -> str:
    """
    記事 HTML にパターン CTA を最大 3 箇所挿入して返す。

    挿入位置（元 HTML の位置で計算し、後ろ→前の順で挿入してインデックスずれを防ぐ）:
        1. 「この記事のポイント」ブロック（wp:loos/cap-block）直後（常に）
        2. 案件名を含む最後の段落ブロック直後（該当段落が見つかった場合のみ）
        3. 記事末尾（常に）

    複数案件がある場合は呼び出し元 match_pattern() がスコア最高の 1 件を選ぶ。

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

    original_len = len(article_html)

    # --- 元 HTML で挿入位置をすべて計算 ---

    # 位置①: 「この記事のポイント」直後
    points_pos = _find_points_block_end(article_html)

    # 位置②: 案件言及段落直後
    # 末尾から 50 字以内（＝言及段落が記事の最終段落）は末尾挿入と隣接するためスキップ
    mention_pos = _find_mention_end(article_html, pattern.tokens)
    if mention_pos is not None and mention_pos >= original_len - 50:
        mention_pos = None

    # 位置③: 末尾
    end_pos = original_len

    # --- 後ろ→前の順に挿入（インデックスがずれない） ---

    # ③ 末尾
    article_html = article_html[:end_pos] + cta_block + article_html[end_pos:]
    log.debug("[wp_pattern_fetcher] 記事末尾に挿入")

    # ② 言及段落直後（③より前なので safe）
    if mention_pos is not None:
        article_html = article_html[:mention_pos] + cta_block + article_html[mention_pos:]
        log.debug(f"[wp_pattern_fetcher] 「{pattern.title}」言及段落直後 (pos={mention_pos}) に挿入")
    else:
        log.debug(f"[wp_pattern_fetcher] 「{pattern.title}」の言及が見つからず or 末尾付近のため中間挿入スキップ")

    # ① ポイント直後（最も前なので最後に挿入）
    if points_pos is not None:
        article_html = article_html[:points_pos] + cta_block + article_html[points_pos:]
        log.debug(f"[wp_pattern_fetcher] 「この記事のポイント」直後 (pos={points_pos}) に挿入")
    else:
        log.debug("[wp_pattern_fetcher] 「この記事のポイント」ブロックが見つからず（スキップ）")

    return article_html
