"""
修正3: カニバリ対策 - WP既存記事との重複チェック
"""
import json
import requests
from requests.auth import HTTPBasicAuth
import anthropic
from config import WP_URL, WP_USERNAME, WP_APP_PASSWORD, ANTHROPIC_API_KEY

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# 実行中に全記事タイトルをキャッシュ（何度もAPIを叩かないため）
_all_titles_cache: list[str] | None = None

# 同一セッション内で生成済み・生成予定の記事タイトルを追跡
_session_titles: list[str] = []


def add_session_title(title: str) -> None:
    """生成した記事タイトルをセッションキャッシュに追加する。"""
    if title and title not in _session_titles:
        _session_titles.append(title)


def clear_session_titles() -> None:
    """セッションキャッシュをリセットする（テスト用）。"""
    global _session_titles
    _session_titles = []


def _fetch_all_titles() -> list[str]:
    """WP REST API で全記事タイトルを取得してキャッシュする（最大1000件）。"""
    global _all_titles_cache
    if _all_titles_cache is not None:
        return _all_titles_cache

    titles: list[str] = []
    page = 1
    while True:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD),
            params={"per_page": 100, "page": page, "status": "any", "_fields": "title"},
            timeout=15,
        )
        if resp.status_code == 400:
            break  # ページ超過
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        titles.extend(p["title"]["rendered"] for p in batch)
        if len(batch) < 100:
            break
        page += 1

    _all_titles_cache = titles
    print(f"[cannibal] 既存記事タイトル取得: {len(titles)}件")
    return titles


def check_cannibalization(keyword: str) -> dict:
    """
    既存記事との重複・カニバリを判定する。

    Returns:
        {
            "status": "ok" | "skip" | "differentiate",
            "similar_titles": [str, ...],
            "differentiation_note": str,
        }
    """
    all_titles = _fetch_all_titles()
    if not all_titles:
        return {"status": "ok", "similar_titles": [], "differentiation_note": ""}

    # キーワードの主要語で事前フィルタ（Claude呼び出しを最小化）
    kw_terms = set(keyword.lower().split())

    # WP既存記事 + セッション内生成済みタイトルをまとめて候補に
    all_check_titles = all_titles + _session_titles
    candidates = [
        t for t in all_check_titles
        if any(term in t.lower() for term in kw_terms if len(term) >= 3)
    ]

    # セッション内タイトルは常にチェック対象に含める（キーワードフィルタなし）
    for st in _session_titles:
        if st not in candidates:
            candidates.append(st)

    if not candidates:
        print(f"[cannibal] 「{keyword}」→ ok（類似記事なし）")
        return {"status": "ok", "similar_titles": [], "differentiation_note": ""}

    # 候補が多い場合は先頭20件に絞る（セッション内タイトルは末尾に付くので保持）
    candidates = candidates[:20]
    session_set = set(_session_titles)
    titles_text = "\n".join(
        f"- {t}{'（※今回セッション生成予定）' if t in session_set else ''}"
        for t in candidates
    )

    prompt = f"""あなたはSEOカニバリゼーション判定の専門家です。厳格に判定してください。
新規キーワード: 「{keyword}」

既存・生成予定の記事タイトル（候補）:
{titles_text}

【判定基準（厳格版）】
- skip: 主要キーワードが同じ、検索意図が同じ、内容の50%以上が重複する → スキップ
- differentiate: 関連テーマだが読者層・切り口・深度が異なれば書ける → 差別化
- ok: テーマが明確に異なる、または検索意図が完全に別 → 問題なし

「似ているかも」程度なら differentiate にしてください。
「ほぼ同一コンテンツになる」場合のみ skip にしてください。

JSONのみ返してください（説明不要）:
{{"status":"ok"|"skip"|"differentiate","similar_titles":["類似タイトル..."],"differentiation_note":"差別化案（differentiateのみ）"}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        result = json.loads(raw)
        status = result.get("status", "ok")
        n_similar = len(result.get("similar_titles", []))
        note = result.get("differentiation_note", "")
        print(f"[cannibal] 「{keyword}」→ {status}" +
              (f"（類似{n_similar}件）" if n_similar else "") +
              (f" ヒント: {note}" if note else ""))
        return result
    except Exception:
        return {"status": "ok", "similar_titles": [], "differentiation_note": ""}
