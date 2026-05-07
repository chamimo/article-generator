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

def _to_hiragana(text: str) -> str:
    """カタカナ（ァ-ヶ）をひらがなに変換する（マッチング用）。"""
    return "".join(
        chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c
        for c in text
    )


def _tokenize(text: str) -> frozenset[str]:
    """NFKC正規化→カタカナ→ひらがな変換→小文字→スペース分割 で2文字以上のトークンを返す。"""
    normalized = _to_hiragana(unicodedata.normalize("NFKC", text).lower())
    return frozenset(t for t in re.split(r"[\s\-_・/【】「」()（）]+", normalized) if len(t) >= 2)


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

def match_pattern(
    keyword: str,
    patterns: list[PatternItem],
    asp_names: list[str] | None = None,
) -> PatternItem | None:
    """
    キーワードに最も関連するパターンを返す。

    スコア計算:
        - 完全一致トークン × 2 点
        - サブストリング一致（KWトークンがパターントークンに含まれる、またはその逆）× 1 点

    マッチ優先順位:
        1. キーワードトークン ↔ パターンタイトルのスコアマッチ（スコア ≥ 1）
        2. スコア 0 かつ asp_names が渡された場合 → アフィリ案件名 ↔ パターンタイトルでマッチ
        3. どちらもスコア 0 → None（挿入しない）

    Returns:
        PatternItem | None
    """
    if not patterns:
        return None

    def _score(query_tokens: frozenset[str], pat: PatternItem) -> int:
        exact  = len(query_tokens & pat.tokens)
        # フルトークン包含（短いトークンが長いトークンに含まれる）
        substr = sum(
            1 for qt in query_tokens for pt in pat.tokens
            if qt in pt or pt in qt
        )
        # 3文字以上の共通部分文字列（日本語複合語の区切りなし結合に対応）
        common = sum(
            1 for qt in query_tokens for pt in pat.tokens
            if len(qt) >= 3 and any(qt[i:i+3] in pt for i in range(len(qt) - 2))
            and qt not in pt and pt not in qt  # substrで既にカウント済みを除外
        )
        return exact * 2 + substr + common

    # ① キーワードによるマッチ
    kw_tokens = _tokenize(keyword)
    best: PatternItem | None = None
    best_score = 0

    if kw_tokens:
        for pat in patterns:
            s = _score(kw_tokens, pat)
            if s > best_score:
                best_score = s
                best = pat

    if best_score > 0:
        log.debug(
            f"[wp_pattern_fetcher] KW={keyword!r} → パターン「{best.title}」 (score={best_score})"
        )
        return best

    # ② アフィリ案件名によるフォールバックマッチ
    if asp_names:
        for name in asp_names:
            name_tokens = _tokenize(name)
            if not name_tokens:
                continue
            for pat in patterns:
                s = _score(name_tokens, pat)
                if s > best_score:
                    best_score = s
                    best = pat

        if best_score > 0:
            log.debug(
                f"[wp_pattern_fetcher] KW={keyword!r} → ASP案件名マッチ → "
                f"パターン「{best.title}」 (score={best_score})"
            )
            return best

    # ③ マッチなし
    log.debug(f"[wp_pattern_fetcher] KW={keyword!r} → 関連パターンなし（挿入スキップ）")
    return None


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

    トークンは _tokenize() で生成（NFKC→ひらがな→小文字）済みのため、
    ブロック本文も同じパイプラインで正規化してから比較する。
    """
    search_terms = sorted(
        (t for t in tokens if len(t) >= 2),
        key=len, reverse=True,
    )[:8]
    if not search_terms:
        return None

    mention_end: int | None = None
    for m in _WP_PARA_BLOCK.finditer(article_html):
        # トークンと同じ正規化（NFKC→ひらがな→小文字）を適用して比較
        block_norm = _to_hiragana(
            unicodedata.normalize("NFKC", m.group()).lower()
        )
        if any(t in block_norm for t in search_terms):
            mention_end = m.end()

    return mention_end


# heading ブロック開始タグ（H2/H3 どちらでも）
_ANY_HEADING = re.compile(r'<!-- wp:heading', re.IGNORECASE)

# セクション末尾とみなすブロック閉じタグ
_SECTION_BLOCK_END = re.compile(
    r'<!-- /wp:(?:paragraph|list|columns|group|table)[^>]*-->',
    re.IGNORECASE,
)


def _make_cta_block(pattern: PatternItem) -> str:
    """パターンの CTA ブロック HTML 文字列を生成する。"""
    if pattern.html.strip().startswith("<!-- wp:"):
        return f"\n{pattern.html.strip()}\n"
    return f'\n<!-- wp:block {{"ref":{pattern.id}}} /-->\n'


def insert_per_h3_cta(
    article_html: str,
    patterns: list[PatternItem],
    asp_list: list[dict],
    max_cta: int = 6,
) -> tuple[str, int]:
    """
    各アフィリ案件に対応するパターンをH3セクション末尾に挿入する。

    処理フロー:
        1. asp_list の各案件名でパターンをマッチング（1パターン = 1回まで）
        2. 案件トークンを含む最後の段落の位置を特定
        3. その段落から次の見出しまでの間の最後のブロック直後に挿入

    Returns:
        (更新後HTML, 挿入件数)
    """
    if not patterns or not asp_list:
        return article_html, 0

    # asp_list → (検索トークン, matched_pattern) のリスト
    product_patterns: list[tuple[frozenset[str], PatternItem]] = []
    seen_ids: set[int] = set()
    for item in asp_list:
        name = item.get("name", "")
        if not name:
            continue
        pat = match_pattern(name, patterns)
        if pat is None or pat.id in seen_ids:
            continue
        search_tokens = _tokenize(name) | pat.tokens
        product_patterns.append((search_tokens, pat))
        seen_ids.add(pat.id)

    if not product_patterns:
        return article_html, 0

    # 見出しブロック開始位置の一覧（セクション境界として使用）
    heading_positions = [m.start() for m in _ANY_HEADING.finditer(article_html)]
    heading_positions.append(len(article_html))

    insertions: list[tuple[int, str, int, str]] = []  # (pos, cta_html, pat_id, title)
    used_positions: set[int] = set()

    for tokens, pat in product_patterns:
        if len(insertions) >= max_cta:
            break

        mention_pos = _find_mention_end(article_html, tokens)
        if mention_pos is None:
            continue

        # mention_pos が含まれるセクションの末尾（次の見出し直前）
        section_end = len(article_html)
        for h_pos in heading_positions:
            if h_pos > mention_pos:
                section_end = h_pos
                break

        # mention_pos 〜 section_end の最後のブロック閉じタグ直後を挿入位置とする
        last_end = mention_pos
        for m in _SECTION_BLOCK_END.finditer(article_html, mention_pos, section_end):
            last_end = m.end()
        insert_pos = last_end

        # 近接位置（50文字以内）への二重挿入を避ける
        if any(abs(insert_pos - p) < 50 for p in used_positions):
            continue

        insertions.append((insert_pos, _make_cta_block(pat), pat.id, pat.title))
        used_positions.add(insert_pos)

    if not insertions:
        return article_html, 0

    # 後ろ→前の順で挿入してインデックスずれを防ぐ
    for pos, cta, pid, title in sorted(insertions, key=lambda x: x[0], reverse=True):
        article_html = article_html[:pos] + cta + article_html[pos:]
        log.debug(f"[wp_pattern_fetcher] H3末尾CTA: 「{title}」(ID:{pid}, pos={pos})")

    log.info(f"[wp_pattern_fetcher] H3末尾CTA挿入: {len(insertions)}件")
    return article_html, len(insertions)


def insert_pattern_cta(article_html: str, pattern: PatternItem, skip_mention: bool = False) -> str:
    """
    記事 HTML にパターン CTA を最大 3 箇所挿入して返す。

    挿入位置（元 HTML の位置で計算し、後ろ→前の順で挿入してインデックスずれを防ぐ）:
        1. 「この記事のポイント」ブロック（wp:loos/cap-block）直後（常に）
        2. 案件名を含む最後の段落ブロック直後（skip_mention=False かつ該当段落が見つかった場合のみ）
        3. 記事末尾（常に）

    skip_mention=True の場合は②をスキップ（insert_per_h3_cta と併用する際に重複を避けるため）。

    Returns:
        str  挿入済みの記事 HTML
    """
    if not pattern.html.strip():
        log.debug("[wp_pattern_fetcher] パターン HTML が空のため挿入をスキップ")
        return article_html

    cta_block = _make_cta_block(pattern)

    original_len = len(article_html)

    # --- 元 HTML で挿入位置をすべて計算 ---

    # 位置①: 「この記事のポイント」直後
    points_pos = _find_points_block_end(article_html)

    # 位置②: 案件言及段落直後（skip_mention=True の場合はスキップ）
    mention_pos = None
    if not skip_mention:
        mention_pos = _find_mention_end(article_html, pattern.tokens)
        # 末尾から 50 字以内（＝末尾挿入と隣接）はスキップ
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

    # ① ポイント直後（最も前なので最後に挿入）
    if points_pos is not None:
        article_html = article_html[:points_pos] + cta_block + article_html[points_pos:]
        log.debug(f"[wp_pattern_fetcher] 「この記事のポイント」直後 (pos={points_pos}) に挿入")
    else:
        log.debug("[wp_pattern_fetcher] 「この記事のポイント」ブロックが見つからず（スキップ）")

    return article_html
