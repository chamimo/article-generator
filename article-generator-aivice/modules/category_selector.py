"""
キーワードから最適なWordPressカテゴリIDをルールベースで選択する（API不使用）。

スコアリング方式:
  カテゴリ名を語単位に分割し、keyword + article_title に含まれる語の長さを合算。
  日本語(漢字・かな)は2文字以上、英数字混じりは3文字以上をマッチ対象とする。
  最高スコアのカテゴリを選択する。
"""
import re
import requests
from modules import wp_context

_category_cache: list[dict] | None = None
EXCLUDE_IDS = {1, 1405, 1408}

# 日本語文字（漢字・ひらがな・カタカナ）のみで構成される文字列を判定
_JA_ONLY_RE = re.compile(r'^[぀-鿿]+$')


def fetch_categories() -> list[dict]:
    """WordPress REST APIから全カテゴリを取得してキャッシュする。"""
    global _category_cache
    if _category_cache is not None:
        return _category_cache

    r = requests.get(
        f"{wp_context.get_wp_url()}/wp-json/wp/v2/categories?per_page=100",
        auth=wp_context.get_auth(),
        timeout=10,
    )
    r.raise_for_status()
    _category_cache = [{"id": c["id"], "name": c["name"], "count": c.get("count", 0)} for c in r.json()]
    print(f"[category_selector] カテゴリ取得: {len(_category_cache)}件")
    return _category_cache


def _min_len(term: str) -> int:
    """日本語のみなら2文字、英数字混じりは3文字を最低マッチ長とする。"""
    return 2 if _JA_ONLY_RE.match(term) else 3


def _score(keyword: str, article_title: str, category_name: str) -> int:
    """
    キーワード + 記事タイトルとカテゴリ名の一致スコアを返す。

    2方向マッチ:
      方向1: カテゴリ名の語がテキストに含まれる → len*2点
      方向2: テキストの語がカテゴリ名に含まれる → len点
    日本語(漢字・かな)は2文字以上、英数字混じりは3文字以上をマッチ対象とする。
    """
    text = f"{keyword} {article_title}".lower()
    cat  = category_name.lower()

    score = 0
    # 方向1: カテゴリ側の語がテキストに含まれる
    for term in re.split(r'[・/（）()\s　]+', cat):
        if len(term) >= _min_len(term) and term in text:
            score += len(term) * 2
    # 方向2: テキスト側の語がカテゴリ名に含まれる
    for word in re.split(r'[\s　]+', text):
        if len(word) >= _min_len(word) and word in cat:
            score += len(word)
    return score


def select_category(keyword: str, article_title: str = "") -> int:
    """
    キーワードと記事タイトルから最適なカテゴリIDを返す。

    Returns:
        WordPress カテゴリID（int）
    """
    categories = fetch_categories()
    candidates = [c for c in categories if c["id"] not in EXCLUDE_IDS]

    # 除外後に候補が0件の場合（カテゴリ未整備サイトなど）は全カテゴリから選ぶ
    if not candidates:
        candidates = categories if categories else [{"id": 1, "name": "未分類", "count": 0}]

    scored = sorted(
        candidates,
        key=lambda c: _score(keyword, article_title, c["name"]),
        reverse=True,
    )

    best = scored[0]
    best_score = _score(keyword, article_title, best["name"])

    if best_score == 0:
        # スコアゼロ（完全不一致）→ blog_config の default_fallback_category を優先
        fallback_name = wp_context.get_default_fallback_category()
        if fallback_name:
            named = next((c for c in candidates if c["name"] == fallback_name), None)
            if named:
                print(f"[category_selector] 「{keyword}」→ マッチなし、設定フォールバック: {named['name']}({named['id']})")
                return named["id"]
        # 設定がない・見つからない場合は記事数最多カテゴリ
        fallback = max(candidates, key=lambda c: c.get("count", 0))
        print(f"[category_selector] 「{keyword}」→ マッチなし、フォールバック: {fallback['name']}({fallback['id']})")
        return fallback["id"]

    print(f"[category_selector] 「{keyword}」→ {best['name']}({best['id']}) score={best_score}")
    return best["id"]
