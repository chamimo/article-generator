"""
体験談フェッチャー
Media OS 共通シート「EXPERIENCE｜体験談」から体験談を読み込み、
キーワードに関連するものを SWELL balloon ブロックとして返す。

シート構造（A〜I列）:
  A: blog       (ブログ name。例: workup-ai, hataraku。空欄=全ブログ共通)
  B: keyword    (マッチング用。完全一致優先。空欄=カテゴリ・ブログのみでマッチ)
  C: category   (カテゴリマッチング用)
  D: priority   (A / B / C)
  E: type       (review / caution / failure / tips)
  F: author     (体験者属性。例: 30代女性・主婦。空欄=typeラベルにフォールバック)
  G: enabled    (TRUE / FALSE。FALSE の行は使用しない)
  H: created_at (記録日。例: 2026-05-30)
  I: comment    (実際の体験談テキスト)
"""
from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials

_SHEET_NAME = "EXPERIENCE｜体験談"
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_cache: list[dict] | None = None
_cache_ss_id: str | None = None

_TYPE_NAMES = {
    "review":  "体験談",
    "caution": "注意点",
    "failure": "体験談",
    "tips":    "実践者",
}


def _load(ss_id: str, credentials_path: str) -> list[dict]:
    global _cache, _cache_ss_id
    if _cache is not None and _cache_ss_id == ss_id:
        return _cache

    try:
        creds = Credentials.from_service_account_file(credentials_path, scopes=_SCOPES)
        gc = gspread.authorize(creds)
        ss = gc.open_by_key(ss_id)
        try:
            ws = ss.worksheet(_SHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            # シートが未作成の場合は自動作成してヘッダーを書き込む
            ws = ss.add_worksheet(title=_SHEET_NAME, rows=1000, cols=9)
            ws.append_row(
                ["blog", "keyword", "category", "priority", "type",
                 "author", "enabled", "created_at", "comment"],
                value_input_option="USER_ENTERED",
            )
            print(f"[testimonial_fetcher] シートを自動作成しました: {_SHEET_NAME}")
            _cache = []
            _cache_ss_id = ss_id
            return _cache
        rows = ws.get_all_values()

        if len(rows) < 2:
            _cache = []
            _cache_ss_id = ss_id
            return _cache

        result = []
        for row in rows[1:]:  # skip header
            if len(row) < 9 or not row[8].strip():
                continue
            # enabled列が明示的に FALSE の行はスキップ
            if row[6].strip().upper() == "FALSE":
                continue
            result.append({
                "blog":       row[0].strip(),
                "keyword":    row[1].strip(),
                "category":   row[2].strip(),
                "priority":   row[3].strip().upper() or "C",
                "type":       row[4].strip().lower() or "review",
                "author":     row[5].strip(),
                "enabled":    row[6].strip(),
                "created_at": row[7].strip(),
                "comment":    row[8].strip(),
            })

        _cache = result
        _cache_ss_id = ss_id
        print(f"[testimonial_fetcher] {len(result)}件読み込み完了 ({_SHEET_NAME})")
    except Exception as e:
        print(f"[testimonial_fetcher] ⚠️ 読み込みエラー: {e}")
        _cache = []
        _cache_ss_id = ss_id

    return _cache


def get_relevant(keyword: str, blog_name: str, ss_id: str, credentials_path: str,
                 max_count: int = 3) -> list[dict]:
    """
    キーワード・ブログに関連する体験談を最大 max_count 件返す。
    マッチング優先度: keyword一致 > category一致 > blog一致のみ
    同優先度内は A priority 優先、次いで行順
    blog列が空欄のエントリは全ブログに適用される
    """
    entries = _load(ss_id, credentials_path)
    if not entries:
        return []

    kw_lower = keyword.lower()
    blog_lower = blog_name.lower()
    priority_order = {"A": 0, "B": 1, "C": 2}

    scored: list[tuple[int, int, dict]] = []
    for e in entries:
        # blog filter: 空欄=全ブログ共通、指定あり=一致のみ
        if e["blog"] and e["blog"].lower() != blog_lower:
            continue

        match_score = 0
        if e["keyword"] and e["keyword"].lower() in kw_lower:
            match_score = 3
        elif e["keyword"] and kw_lower in e["keyword"].lower():
            match_score = 2
        elif e["category"] and e["category"].lower() in kw_lower:
            match_score = 1
        # match_score=0: blog一致のみ（or 全ブログ共通エントリ）

        pri = priority_order.get(e["priority"], 2)
        scored.append((-match_score, pri, e))

    scored.sort(key=lambda x: (x[0], x[1]))
    return [e for _, _, e in scored[:max_count]]


def build_balloon_blocks(entries: list[dict]) -> str:
    """
    体験談エントリのリストを SWELL speech-balloon Gutenberg ブロック HTML に変換する。
    左向き・アイコン画像なし・type別ラベル表示
    """
    if not entries:
        return ""

    blocks = []
    for e in entries:
        # author が設定されていれば balloon 表示名に使う（なければ type ラベル）
        icon_name = e.get("author") or _TYPE_NAMES.get(e["type"], "体験談")
        text = e["comment"].replace("<", "&lt;").replace(">", "&gt;")
        block = (
            f'<!-- wp:loos/speech-balloon {{"icon_url":"","icon_name":"{icon_name}",'
            f'"icon_pos":"l","balloon_shape":"talking"}} -->\n'
            f'<div class="swell-block-speechBalloon">'
            f'<div class="speech-person -l -talking">'
            f'<p class="speech-name">{icon_name}</p>'
            f'<div class="speech-icon"><img src="" alt="{icon_name}"/></div>'
            f'</div>'
            f'<div class="speech-balloon talking"><!-- wp:paragraph -->\n'
            f'<p>{text}</p>\n'
            f'<!-- /wp:paragraph --></div></div>\n'
            f'<!-- /wp:loos/speech-balloon -->'
        )
        blocks.append(block)

    return "\n\n".join(blocks)


def build_prompt_section(keyword: str, blog_name: str, ss_id: str, credentials_path: str) -> str:
    """
    キーワードに関連する体験談をプロンプト用テキストに変換して返す。
    Claudeへのコンテキスト提供用。データがない場合は空文字列を返す。
    """
    entries = get_relevant(keyword, blog_name, ss_id, credentials_path)
    if not entries:
        return ""

    type_labels = {"review": "使用感", "caution": "注意点", "failure": "失敗談", "tips": "コツ"}
    lines = [
        "## 実際の読者体験談（記事内で自然に活用してください）",
        "以下の体験談を参考に、H3本文やFAQに具体的なエピソードとして組み込んでください。",
        "",
    ]
    for i, e in enumerate(entries, 1):
        label = type_labels.get(e["type"], "体験談")
        author_tag = f"（{e['author']}）" if e.get("author") else ""
        lines.append(f"{i}. 【{label}】{author_tag}{e['comment']}")
        lines.append("")

    return "\n".join(lines) + "\n"


def suggest_candidates(
    keyword: str,
    blog_name: str,
    category: str,
    ss_id: str,
    credentials_path: str,
    threshold: int = 2,
) -> dict | None:
    """
    体験談が threshold 件未満のとき、Haiku API で4タイプの候補を生成して返す。
    足りている場合は None を返す。

    Returns:
        {
            "existing_count": int,
            "suggestions": {
                "review":  {"author": "（仮）...", "comment": "..."},
                "caution": {"author": "（仮）...", "comment": "..."},
                "failure": {"author": "（仮）...", "comment": "..."},
                "tips":    {"author": "（仮）...", "comment": "..."},
            }
        }
        or None if existing_count >= threshold
    """
    existing = get_relevant(keyword, blog_name, ss_id, credentials_path, max_count=threshold)
    existing_count = len(existing)
    if existing_count >= threshold:
        return None

    try:
        import json
        import anthropic
        from config import ANTHROPIC_API_KEY
        from modules.api_guard import record_usage

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        prompt = f"""以下のキーワードに関連するブログ記事の読者体験談を4種類生成してください。

ブログ: {blog_name}
キーワード: {keyword}
カテゴリ: {category or "未分類"}

ルール:
- 実際の読者が書いたような自然な一人称（です・ます調）
- 60〜120文字程度
- 具体的なエピソードや感想を含む
- 誇張・虚偽のない現実的な内容
- 著者は架空の属性（年代・性別・職業など）を設定

以下の4タイプを1件ずつ、JSONのみ返してください（余分なテキスト不要）:
- review: 使用感・感想（実際に使ってみてどうだったか）
- caution: 注意点・気をつけること（失敗しそうになったこと）
- failure: 失敗談（うまくいかなかった具体的な経験）
- tips: コツ・おすすめの使い方（こうすると上手くいく）

出力形式:
{{
  "review":  {{"author": "30代・会社員", "comment": "..."}},
  "caution": {{"author": "20代・フリーランス", "comment": "..."}},
  "failure": {{"author": "40代・主婦", "comment": "..."}},
  "tips":    {{"author": "30代・Webライター", "comment": "..."}}
}}"""

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        record_usage("claude-haiku-4-5-20251001",
                     resp.usage.input_tokens, resp.usage.output_tokens)

        raw = resp.content[0].text.strip()
        # JSONブロック抽出（```json ... ``` があれば除去）
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)

        # author に「（仮）」プレフィックスを付与
        suggestions: dict = {}
        for type_key in ("review", "caution", "failure", "tips"):
            entry = data.get(type_key, {})
            suggestions[type_key] = {
                "author":  f"（仮）{entry.get('author', '属性未設定')}",
                "comment": entry.get("comment", ""),
            }

        print(f"[testimonial_fetcher] 候補生成完了: {keyword} (既存{existing_count}件)")
        return {"existing_count": existing_count, "suggestions": suggestions}

    except Exception as e:
        print(f"[testimonial_fetcher] ⚠️ 候補生成エラー: {e}")
        return None


def write_to_review_queue(
    blog_name: str,
    keyword: str,
    category: str,
    suggestions: dict,
    ss_id: str,
    credentials_path: str,
) -> int:
    """
    体験談候補を ReviewQueue シートに追記する。
    enabled=FALSE, status=pending で書き込む。

    Returns: 追記した行数（失敗時は 0）
    """
    _QUEUE_SHEET = "EXPERIENCE｜ReviewQueue"
    try:
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        creds = Credentials.from_service_account_file(credentials_path, scopes=_SCOPES)
        gc = gspread.authorize(creds)
        ss = gc.open_by_key(ss_id)
        try:
            ws = ss.worksheet(_QUEUE_SHEET)
        except gspread.exceptions.WorksheetNotFound:
            ws = ss.add_worksheet(title=_QUEUE_SHEET, rows=2000, cols=10)
            print(f"[testimonial_fetcher] シートを自動作成しました: {_QUEUE_SHEET}")

        # ヘッダー確認（内容で判断。新規シートや空シートでも確実に書き込む）
        _QUEUE_HEADER = ["blog", "keyword", "category", "priority", "type",
                         "author", "enabled", "created_at", "comment", "status"]
        existing = ws.get_all_values()
        if not existing or existing[0][:10] != _QUEUE_HEADER:
            ws.insert_row(_QUEUE_HEADER, index=1, value_input_option="USER_ENTERED")

        count = 0
        for type_key in ("review", "caution", "failure", "tips"):
            c = suggestions.get(type_key, {})
            if not c.get("comment"):
                continue
            ws.append_row(
                [blog_name, keyword, category, "B", type_key,
                 c["author"], "FALSE", today, c["comment"], "pending"],
                value_input_option="USER_ENTERED",
            )
            count += 1

        print(f"[testimonial_fetcher] ReviewQueue に{count}件追記: {keyword}")
        return count
    except Exception as e:
        print(f"[testimonial_fetcher] ⚠️ ReviewQueue 書き込みエラー: {e}")
        return 0


def promote_approved(ss_id: str, credentials_path: str) -> tuple[int, int]:
    """
    ReviewQueue から status=approved かつ enabled=TRUE の行を
    EXPERIENCE｜体験談 に昇格させる。

    重複チェック: keyword + type + comment がすべて一致する行はスキップ
    昇格後: ReviewQueue 側の status を "promoted" に更新（行は削除しない）
    キャッシュをクリアして次回読み込みで新データを反映する。

    Returns: (promoted_count, skipped_count)
    """
    _QUEUE_SHEET = "EXPERIENCE｜ReviewQueue"

    try:
        creds = Credentials.from_service_account_file(credentials_path, scopes=_SCOPES)
        gc = gspread.authorize(creds)
        ss = gc.open_by_key(ss_id)

        try:
            queue_ws = ss.worksheet(_QUEUE_SHEET)
        except gspread.exceptions.WorksheetNotFound:
            print(f"[testimonial_fetcher] {_QUEUE_SHEET} が存在しません")
            return 0, 0

        try:
            exp_ws = ss.worksheet(_SHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            exp_ws = ss.add_worksheet(title=_SHEET_NAME, rows=1000, cols=9)
            exp_ws.append_row(
                ["blog", "keyword", "category", "priority", "type",
                 "author", "enabled", "created_at", "comment"],
                value_input_option="USER_ENTERED",
            )
            print(f"[testimonial_fetcher] シートを自動作成しました: {_SHEET_NAME}")

        queue_rows = queue_ws.get_all_values()
        exp_rows   = exp_ws.get_all_values()

        if len(queue_rows) < 2:
            print("[testimonial_fetcher] ReviewQueue: 処理対象なし")
            return 0, 0

        # 既存体験談の重複チェックキー: (keyword下, type下, comment)
        existing_keys: set[tuple[str, str, str]] = set()
        for row in exp_rows[1:]:
            if len(row) >= 9 and row[8].strip():
                existing_keys.add((
                    row[1].strip().lower(),
                    row[4].strip().lower(),
                    row[8].strip(),
                ))

        promoted = 0
        skipped  = 0
        # ReviewQueueの列インデックス（0始まり）:
        #   blog=0, keyword=1, category=2, priority=3, type=4,
        #   author=5, enabled=6, created_at=7, comment=8, status=9
        STATUS_COL = 10  # gspread は 1始まり

        # 更新対象をまとめてバッチ処理（Sheets API コール数削減）
        status_updates: list[tuple[int, str]] = []  # (1-indexed row, new_status)

        for i, row in enumerate(queue_rows[1:], start=2):
            if len(row) < 10:
                continue
            if row[9].strip().lower() != "approved":
                continue
            if row[6].strip().upper() != "TRUE":
                continue

            keyword  = row[1].strip()
            type_key = row[4].strip().lower()
            comment  = row[8].strip()
            dup_key  = (keyword.lower(), type_key, comment)

            if dup_key in existing_keys:
                print(f"[testimonial_fetcher] スキップ（重複）: {keyword} / {type_key}")
                status_updates.append((i, "promoted"))
                skipped += 1
                continue

            # EXPERIENCE｜体験談 に追記（enabled=TRUE）
            exp_ws.append_row(
                [row[0], keyword, row[2], row[3], type_key,
                 row[5], "TRUE", row[7], comment],
                value_input_option="USER_ENTERED",
            )
            existing_keys.add(dup_key)
            status_updates.append((i, "promoted"))
            promoted += 1
            print(f"[testimonial_fetcher] 昇格: {keyword} / {type_key}")

        # ReviewQueue のステータスをまとめて更新
        if status_updates:
            for row_num, new_status in status_updates:
                queue_ws.update_cell(row_num, STATUS_COL, new_status)

        # キャッシュをクリア（次回記事生成で昇格分を反映）
        clear_cache()

        print(f"[testimonial_fetcher] 昇格完了: {promoted}件昇格 / {skipped}件スキップ（重複）")
        return promoted, skipped

    except Exception as e:
        print(f"[testimonial_fetcher] ⚠️ 昇格処理エラー: {e}")
        return 0, 0


def clear_cache() -> None:
    global _cache, _cache_ss_id
    _cache = None
    _cache_ss_id = None
