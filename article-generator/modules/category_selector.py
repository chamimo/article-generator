"""
キーワードをClaude APIで分析し、最適なWordPressカテゴリIDを自動選択する
"""
import anthropic
import requests
from requests.auth import HTTPBasicAuth
from config import ANTHROPIC_API_KEY, WP_URL, WP_USERNAME, WP_APP_PASSWORD

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# カテゴリ一覧のキャッシュ（実行中は再取得しない）
_category_cache: list[dict] | None = None


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


def select_category(keyword: str, article_title: str = "") -> int:
    """
    キーワードと記事タイトルからClaudeが最適なカテゴリIDを返す。

    Returns:
        WordPress カテゴリID（int）
    """
    categories = fetch_categories()

    # 「未分類」(ID:1)と「PickUP」「nanobanana」などの管理用カテゴリは候補から除外
    EXCLUDE_IDS = {1, 1405, 1408}
    candidates = [c for c in categories if c["id"] not in EXCLUDE_IDS]

    category_list = "\n".join(f"- ID:{c['id']} 「{c['name']}」" for c in candidates)

    prompt = f"""あなたはAIツール・生成AI情報メディア「AIVice」の編集者です。
以下のカテゴリ一覧の中から、キーワードに最も適したカテゴリを1つ選んでください。

## カテゴリ一覧
{category_list}

## 判定対象
- キーワード: {keyword}
- 記事タイトル: {article_title or "（未定）"}

## 回答ルール
- 必ずカテゴリIDの数字のみ返してください（例: 1371）
- 説明や前置きは不要です
- 該当カテゴリが見当たらない場合は、最も近いものを選んでください
"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # 数字のみ抽出
    digits = "".join(filter(str.isdigit, raw))
    if not digits:
        print(f"[category_selector] 解析失敗 ('{raw}')、未分類(1)を使用")
        return 1

    selected_id = int(digits)

    # 有効なIDか検証
    valid_ids = {c["id"] for c in categories}
    if selected_id not in valid_ids:
        print(f"[category_selector] 無効なID({selected_id})、未分類(1)を使用")
        return 1

    name = next(c["name"] for c in categories if c["id"] == selected_id)
    print(f"[category_selector] 「{keyword}」→ ID:{selected_id}「{name}」")
    return selected_id
