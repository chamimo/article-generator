"""
キーワードから最適なWordPressカテゴリIDをルールベースで選択する。

スコアリング方式:
  カテゴリ名を語単位に分割し、keyword + article_title に含まれる語の長さを合算。
  日本語(漢字・かな)は2文字以上、英数字混じりは3文字以上をマッチ対象とする。
  最高スコアが MIN_SCORE 未満の場合はカテゴリを新規作成して未分類を回避する。
"""
import re
import requests
from modules import wp_context

# ブログ切り替え時のキャッシュ汚染を防ぐため WP_URL も一緒に保持する
_category_cache: list[dict] | None = None
_cache_wp_url: str = ""

EXCLUDE_IDS = {1, 1405, 1408}

# このスコア未満なら「マッチなし」とみなして新規カテゴリを作成する
MIN_SCORE = 4

# 日本語文字（漢字・ひらがな・カタカナ）のみで構成される文字列を判定
_JA_ONLY_RE = re.compile(r'^[぀-鿿]+$')


def fetch_categories(force: bool = False) -> list[dict]:
    """WordPress REST APIから全カテゴリを取得してキャッシュする。"""
    global _category_cache, _cache_wp_url
    current_url = wp_context.get_wp_url()
    # ブログが切り替わったらキャッシュをリセット
    if force or _category_cache is None or _cache_wp_url != current_url:
        r = requests.get(
            f"{current_url}/wp-json/wp/v2/categories?per_page=100",
            auth=wp_context.get_auth(),
            timeout=10,
        )
        r.raise_for_status()
        _category_cache = [{"id": c["id"], "name": c["name"], "count": c.get("count", 0)} for c in r.json()]
        _cache_wp_url = current_url
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
    """
    text = f"{keyword} {article_title}".lower()
    cat  = category_name.lower()

    score = 0
    for term in re.split(r'[・/（）()\s　]+', cat):
        if len(term) >= _min_len(term) and term in text:
            score += len(term) * 2
    for word in re.split(r'[\s　]+', text):
        if len(word) >= _min_len(word) and word in cat:
            score += len(word)
    return score


def _hint_score(keyword: str, article_title: str, category_name: str) -> int:
    """blog_config の category_keywords ヒントマップを使ったスコアを返す。"""
    hints: dict = wp_context.get_category_keywords()
    if not hints:
        return 0
    kw_list = hints.get(category_name)
    if not kw_list:
        return 0
    text = f"{keyword} {article_title}".lower()
    score = 0
    for hint in kw_list:
        h = hint.lower()
        if h in text:
            score += len(h) * 3
    return score


def _suggest_category_name(keyword: str, article_title: str) -> str:
    """Claude Haiku でカテゴリ名を提案する（最大12文字の日本語）。"""
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY
        meta = wp_context.get_blog_meta()
        genre = meta.get("genre", "観光・旅行")
        c = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = c.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            messages=[{
                "role": "user",
                "content": (
                    f"ブログジャンル: {genre}\n"
                    f"キーワード: {keyword}\n"
                    f"記事タイトル: {article_title}\n"
                    "この記事に最も適したWordPressカテゴリ名を1つだけ答えてください。"
                    "カテゴリ名は4〜12文字の日本語で、簡潔に。説明は不要。カテゴリ名のみ回答:"
                ),
            }],
        )
        name = msg.content[0].text.strip().strip("「」『』【】")[:15]
        print(f"[category_selector] 新規カテゴリ提案: 「{name}」")
        return name
    except Exception as e:
        print(f"[category_selector] カテゴリ提案エラー: {e}")
        # フォールバック: キーワードの先頭2語
        words = re.split(r'[\s　・]+', keyword)
        return "".join(words[:2])[:10] or "その他"


def _create_wp_category(name: str) -> int:
    """WP APIでカテゴリを新規作成し、IDを返す。既存の場合はそのIDを返す。"""
    global _category_cache
    # キャッシュ内に同名があればそちらを使う
    if _category_cache:
        existing = next((c for c in _category_cache if c["name"] == name), None)
        if existing:
            print(f"[category_selector] 既存カテゴリを使用: 「{name}」({existing['id']})")
            return existing["id"]

    r = requests.post(
        f"{wp_context.get_wp_url()}/wp-json/wp/v2/categories",
        auth=wp_context.get_auth(),
        json={"name": name},
        timeout=10,
    )
    if r.status_code in (200, 201):
        data = r.json()
        new_cat = {"id": data["id"], "name": data["name"], "count": 0}
        if _category_cache is not None:
            _category_cache.append(new_cat)
        print(f"[category_selector] カテゴリ新規作成: 「{name}」(ID={data['id']})")
        return data["id"]
    elif r.status_code == 400:
        # 「term_exists」エラー = 同名が既に存在する
        err = r.json()
        if err.get("data", {}).get("term_id"):
            existing_id = int(err["data"]["term_id"])
            print(f"[category_selector] 既存カテゴリ(API): 「{name}」(ID={existing_id})")
            return existing_id
    r.raise_for_status()
    return 1  # フェイルセーフ


def select_category(keyword: str, article_title: str = "") -> int:
    """
    キーワードと記事タイトルから最適なカテゴリIDを返す。
    スコアが MIN_SCORE 未満の場合は新規カテゴリを作成して未分類を回避する。

    Returns:
        WordPress カテゴリID（int）
    """
    categories = fetch_categories()
    candidates = [c for c in categories if c["id"] not in EXCLUDE_IDS]

    if not candidates:
        candidates = categories if categories else []

    def total_score(c: dict) -> int:
        return _score(keyword, article_title, c["name"]) + _hint_score(keyword, article_title, c["name"])

    if candidates:
        scored = sorted(candidates, key=total_score, reverse=True)
        best = scored[0]
        best_score = total_score(best)
    else:
        best_score = 0

    if best_score >= MIN_SCORE:
        print(f"[category_selector] 「{keyword}」→ {best['name']}({best['id']}) score={best_score}")
        return best["id"]

    # スコア不足 → 設定フォールバックを試みる
    fallback_name = wp_context.get_default_fallback_category()
    if fallback_name:
        named = next((c for c in candidates if c["name"] == fallback_name), None)
        if named:
            print(f"[category_selector] 「{keyword}」→ 設定フォールバック: {named['name']}({named['id']})")
            return named["id"]

    # スコア不足 & フォールバックなし → 新規カテゴリを作成
    new_name = _suggest_category_name(keyword, article_title)
    return _create_wp_category(new_name)
