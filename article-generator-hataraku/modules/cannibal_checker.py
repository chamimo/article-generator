"""
カニバリ対策 - WP既存記事との重複チェック（ルールベース版・API不使用）

判定方式: Jaccard bigram 類似度 + キーワード包含チェック
  - Jaccard >= SKIP_THRESHOLD        → skip（ほぼ同一コンテンツ）
  - Jaccard >= DIFFERENTIATE_THRESHOLD → differentiate（差別化すれば書ける）
  - Jaccard < DIFFERENTIATE_THRESHOLD  → ok
"""
import re
import requests
from html import unescape
from requests.auth import HTTPBasicAuth
from config import WP_URL, WP_USERNAME, WP_APP_PASSWORD

_all_titles_cache: list[str] | None = None
_session_titles:   list[str] = []

SKIP_THRESHOLD          = 0.35   # Jaccard ≥ この値 → skip
DIFFERENTIATE_THRESHOLD = 0.18   # Jaccard ≥ この値 → differentiate


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
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        titles.extend(unescape(p["title"]["rendered"]) for p in batch)
        if len(batch) < 100:
            break
        page += 1

    _all_titles_cache = titles
    print(f"[cannibal] 既存記事タイトル取得: {len(titles)}件")
    return titles


def _normalize(s: str) -> str:
    s = s.lower()
    return re.sub(r'[！-／：-＠【】「」『』（）・\s\u3000]+', ' ', s).strip()


def _bigrams(s: str) -> set[str]:
    s = _normalize(s)
    return {s[i:i+2] for i in range(len(s) - 1)} if len(s) >= 2 else set(s)


def _jaccard(a: str, b: str) -> float:
    bg_a = _bigrams(a)
    bg_b = _bigrams(b)
    if not bg_a and not bg_b:
        return 1.0
    if not bg_a or not bg_b:
        return 0.0
    return len(bg_a & bg_b) / len(bg_a | bg_b)


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
    all_check  = all_titles + [t for t in _session_titles if t not in all_titles]
    if not all_check:
        return {"status": "ok", "similar_titles": [], "differentiation_note": ""}

    kw_norm  = _normalize(keyword)
    kw_terms = {t for t in kw_norm.split() if len(t) >= 2}
    session_set = set(_session_titles)

    similar: list[tuple[float, str]] = []

    for title in all_check:
        title_norm = _normalize(title)

        # キーワード完全包含（高速パス）
        if kw_norm and kw_norm in title_norm:
            score = 0.9
        elif not any(t in title_norm for t in kw_terms if len(t) >= 3):
            continue
        else:
            score = _jaccard(keyword, title)

        # セッション内タイトルはやや厳しく判定
        if title in session_set:
            score = min(score * 1.2, 1.0)

        if score >= DIFFERENTIATE_THRESHOLD:
            similar.append((score, title))

    similar.sort(reverse=True)

    if not similar:
        print(f"[cannibal] 「{keyword}」→ ok")
        return {"status": "ok", "similar_titles": [], "differentiation_note": ""}

    best_score, best_title = similar[0]

    if best_score >= SKIP_THRESHOLD:
        print(f"[cannibal] 「{keyword}」→ skip（{len(similar)}件, best={best_score:.2f}: {best_title[:40]}）")
        return {
            "status": "skip",
            "similar_titles": [t for _, t in similar[:3]],
            "differentiation_note": "",
        }
    else:
        print(f"[cannibal] 「{keyword}」→ differentiate（best={best_score:.2f}: {best_title[:40]}）")
        return {
            "status": "differentiate",
            "similar_titles": [t for _, t in similar[:3]],
            "differentiation_note": f"「{best_title[:30]}」と類似（類似度{best_score:.2f}）",
        }
