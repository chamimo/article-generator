"""
キーワードから最適なWordPressカテゴリIDをルールベースで選択する（API不使用）。

スコアリング方式:
  カテゴリ名を語単位に分割し、keyword + article_title に含まれる語の長さを合算。
  最高スコアのカテゴリを選択する。
"""
import re
import requests
from requests.auth import HTTPBasicAuth
from config import WP_URL, WP_USERNAME, WP_APP_PASSWORD

_category_cache: list[dict] | None = None
EXCLUDE_IDS = {1, 1405, 1408}


def fetch_categories() -> list[dict]:
    """WordPress REST APIから全カテゴリを取得してキャッシュする。"""
    global _category_cache
    if _category_cache is not None:
        return _category_cache

    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/categories?per_page=100",
        auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD),
        timeout=10,
    )
    r.raise_for_status()
    _category_cache = [{"id": c["id"], "name": c["name"]} for c in r.json()]
    print(f"[category_selector] カテゴリ取得: {len(_category_cache)}件")
    return _category_cache


def _score(keyword: str, article_title: str, category_name: str) -> int:
    """
    キーワード + 記事タイトルとカテゴリ名の一致スコアを返す。

    2方向マッチ:
      方向1: カテゴリ名の語（>=3文字）がテキストに含まれる → len*2点
      方向2: テキストの語（>=3文字）がカテゴリ名に含まれる → len点
    長い語が一致するほど高得点。2文字の曖昧マッチ（"ai"など）を防ぐ。
    """
    text = f"{keyword} {article_title}".lower()
    cat  = category_name.lower()

    score = 0
    # 方向1: カテゴリ側の語がテキストに含まれる
    for term in re.split(r'[・/（）()\s　]+', cat):
        if len(term) >= 3 and term in text:
            score += len(term) * 2
    # 方向2: テキスト側の語がカテゴリ名に含まれる
    for word in re.split(r'[\s\u3000]+', text):
        if len(word) >= 3 and word in cat:
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

    scored = sorted(
        candidates,
        key=lambda c: _score(keyword, article_title, c["name"]),
        reverse=True,
    )

    best = scored[0]
    best_score = _score(keyword, article_title, best["name"])

    if best_score == 0:
        # スコアゼロ（完全不一致）→ 「生成AI・チャット・仕事術」を探してフォールバック
        fallback = next(
            (c for c in candidates if "生成ai" in c["name"].lower() or "チャット" in c["name"].lower()),
            candidates[0],
        )
        print(f"[category_selector] 「{keyword}」→ マッチなし、フォールバック: {fallback['name']}({fallback['id']})")
        return fallback["id"]

    print(f"[category_selector] 「{keyword}」→ {best['name']}({best['id']}) score={best_score}")
    return best["id"]
