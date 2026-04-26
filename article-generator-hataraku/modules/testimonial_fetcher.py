"""
体験談フェッチャー
はた楽ナビのスプレッドシート「体験談」シートから体験談を読み込み、
キーワードに関連するものを記事プロンプトに組み込む。

シート構造（A〜E列）:
  A: キーワード/カテゴリ  (マッチング用。「転職」「副業」など)
  B: 体験者属性           (「30代・男性・製造業」など)
  C: 体験談本文           (実際の体験談テキスト 100〜300字程度)
  D: 検索意図タイプ       (共感系 / 比較系 / 購買直前 ― 空欄可)
  E: 備考                 (任意)
"""
from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials

_SHEET_GID   = 1432910148
_SCOPES      = ["https://www.googleapis.com/auth/spreadsheets"]
_cache: list[dict] | None = None


def _load(ss_id: str, credentials_path: str) -> list[dict]:
    global _cache
    if _cache is not None:
        return _cache

    try:
        creds = Credentials.from_service_account_file(credentials_path, scopes=_SCOPES)
        gc    = gspread.authorize(creds)
        ws    = gc.open_by_key(ss_id).get_worksheet_by_id(_SHEET_GID)
        rows  = ws.get_all_values()

        if len(rows) < 2 or not any(c.strip() for c in rows[1]):
            _cache = []
            return _cache

        result = []
        for row in rows[1:]:  # skip header
            if len(row) < 3 or not row[2].strip():
                continue
            result.append({
                "keyword": row[0].strip() if len(row) > 0 else "",
                "persona": row[1].strip() if len(row) > 1 else "",
                "text":    row[2].strip(),
                "intent":  row[3].strip() if len(row) > 3 else "",
            })

        _cache = result
        print(f"[testimonial_fetcher] {len(result)}件読み込み完了")
    except Exception as e:
        print(f"[testimonial_fetcher] ⚠️ 読み込みエラー: {e}")
        _cache = []

    return _cache


def get_relevant(keyword: str, ss_id: str, credentials_path: str,
                 max_count: int = 3) -> list[dict]:
    """キーワードに関連する体験談を最大 max_count 件返す。"""
    entries = _load(ss_id, credentials_path)
    if not entries:
        return []

    kw_lower = keyword.lower()

    scored: list[tuple[int, dict]] = []
    for e in entries:
        cat   = e["keyword"].lower()
        score = 0
        for cat_word in cat.split():
            if len(cat_word) >= 2 and cat_word in kw_lower:
                score += 2
        for kw_word in kw_lower.split():
            if len(kw_word) >= 2 and kw_word in cat:
                score += 1
        if score > 0:
            scored.append((score, e))

    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:max_count]]


def build_prompt_section(keyword: str, ss_id: str, credentials_path: str) -> str:
    """
    キーワードに関連する体験談をプロンプト用テキストに変換して返す。
    データがない場合は空文字列を返す。
    """
    entries = get_relevant(keyword, ss_id, credentials_path)
    if not entries:
        return ""

    lines = [
        "## 実際の読者体験談（記事内で自然に活用してください）",
        "以下の体験談を参考に、H3本文やFAQに具体的なエピソードとして組み込んでください。",
        "体験者属性と体験談テキストを自然な文脈で引用・アレンジして活用してください。",
        "（引用形式の例：「30代男性の転職経験者によると…」「実際に転職した方から聞いた話では…」）",
        "",
    ]
    for i, e in enumerate(entries, 1):
        persona_tag = f"【{e['persona']}】 " if e["persona"] else ""
        lines.append(f"{i}. {persona_tag}{e['text']}")
        lines.append("")

    return "\n".join(lines) + "\n"


def clear_cache() -> None:
    global _cache
    _cache = None
