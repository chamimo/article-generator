"""
投稿済みフラグをGoogleスプレッドシートに書き込むモジュール

書き込む列（aim列の右隣から）:
  - 投稿ステータス : 「投稿済み」
  - 投稿日         : YYYY/MM/DD
  - 記事URL        : https://workup-ai.com/slug
  - 投稿ID         : WP post ID
  - 使用サブKW     : H3見出しで使ったキーワード（カンマ区切り）

別シート「投稿記事一覧」に1記事1行で詳細を記録する。
"""
from __future__ import annotations

import re
import gspread
from google.oauth2.service_account import Credentials
from datetime import date

from config import GOOGLE_SHEETS_ID, GOOGLE_CREDENTIALS_PATH, SHEETS_ARTICLE_LIST_NAME, SHEETS_LEGEND_NAME, SHEETS_MAIN_SHEET_NAME

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# メインシートに追加する列ヘッダー
_NEW_HEADERS = ["投稿ステータス", "投稿日", "記事URL", "投稿ID", "使用サブKW", "メモ"]

# 投稿記事一覧シートの列定義
_LIST_HEADERS = [
    "投稿日", "公開日", "記事タイトル", "URL", "WP投稿ID",
    "メインKW", "関連KW", "使用サブKW", "カテゴリー", "タグ",
    "文字数（目安）", "記事タイプ", "KWステータス", "ステータス",
]

_ARTICLE_LIST_SHEET_NAME = SHEETS_ARTICLE_LIST_NAME
_LEGEND_SHEET_NAME = SHEETS_LEGEND_NAME

_ws_cache: gspread.Worksheet | None = None
_ss_cache: gspread.Spreadsheet | None = None
_active_ss_id_cache: str | None = None


def _get_spreadsheet() -> gspread.Spreadsheet:
    global _ss_cache, _ws_cache, _active_ss_id_cache
    try:
        from modules import wp_context
        active_ss_id = wp_context.get_candidate_ss_id()
    except Exception:
        active_ss_id = GOOGLE_SHEETS_ID
    if _ss_cache is not None and _active_ss_id_cache == active_ss_id:
        return _ss_cache
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    _ss_cache = gc.open_by_key(active_ss_id)
    _active_ss_id_cache = active_ss_id
    _ws_cache = None  # SSが変わったらワークシートキャッシュもクリア
    return _ss_cache


def _get_worksheet() -> gspread.Worksheet:
    global _ws_cache
    if _ws_cache is not None:
        return _ws_cache
    ss = _get_spreadsheet()
    try:
        from modules import wp_context
        sheet_name = wp_context.get_candidate_sheet()
    except Exception:
        sheet_name = SHEETS_MAIN_SHEET_NAME
    if sheet_name:
        _ws_cache = ss.worksheet(sheet_name)
    else:
        _ws_cache = ss.get_worksheet(0)
    return _ws_cache


def _get_or_create_article_list_sheet() -> gspread.Worksheet:
    """「投稿記事一覧」シートを取得または新規作成し、ヘッダーを保証する。"""
    ss = _get_spreadsheet()
    try:
        ws = ss.worksheet(_ARTICLE_LIST_SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=_ARTICLE_LIST_SHEET_NAME, rows=1000, cols=len(_LIST_HEADERS))
        print(f"[sheets_updater] シート「{_ARTICLE_LIST_SHEET_NAME}」を新規作成")

    # ヘッダー行確認・追加
    first_row = ws.row_values(1)
    if first_row != _LIST_HEADERS:
        ws.update("A1", [_LIST_HEADERS])
        # ヘッダー行を太字・背景色（薄い青）に
        body = {
            "requests": [{
                "repeatCell": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.8, "green": 0.9, "blue": 1.0},
                            "textFormat": {"bold": True},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            }]
        }
        ss.batch_update(body)
        print(f"[sheets_updater] 「{_ARTICLE_LIST_SHEET_NAME}」ヘッダーを設定")

    return ws


def setup_legend_sheet() -> None:
    """「凡例」シートを作成または更新し、背景色・説明を書き込む。"""
    ss = _get_spreadsheet()
    try:
        ws = ss.worksheet(_LEGEND_SHEET_NAME)
        ws.clear()
        print(f"[sheets_updater] シート「{_LEGEND_SHEET_NAME}」をクリアして更新")
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=_LEGEND_SHEET_NAME, rows=30, cols=5)
        print(f"[sheets_updater] シート「{_LEGEND_SHEET_NAME}」を新規作成")

    # ヘッダー行とデータ行
    rows = [
        ["背景色", "ステータス", "説明"],
        ["白（デフォルト）", "未処理", "まだAIM判定されていないキーワード"],
        ["薄いイエロー", "生成待ち", "AIM判定済み・記事生成待ち"],
        ["薄いグレー", "投稿済み", "記事生成・WP投稿完了"],
        ["薄いオレンジ", "カニバリスキップ", "既存記事と内容が重複するためスキップ"],
        [],
        ["追加情報"],
        ["キーワード列", "メインキーワード"],
        ["AIM列", "「aim」と入力するとシステムが処理対象として認識"],
        ["メモ列", "カニバリ理由・差別化メモが自動記入される"],
        ["投稿日・URL・ID", "投稿後に自動記入される"],
    ]
    ws.update("A1", rows, value_input_option="USER_ENTERED")

    # 列幅調整 & スタイル一括設定
    sheet_id = ws.id
    color_map = [
        # (row_index 0-based, red, green, blue)
        (0, 0.27, 0.51, 0.71),   # ヘッダー: 青
        (1, 1.0,  1.0,  1.0),    # 白（デフォルト）
        (2, 1.0,  1.0,  0.6),    # 薄いイエロー
        (3, 211/255, 211/255, 211/255),  # 薄いグレー
        (4, 1.0,  0.8,  0.6),    # 薄いオレンジ
        (6, 0.9,  0.9,  0.9),    # 追加情報ヘッダー: 薄いグレー
    ]

    requests = []

    # 背景色
    for row_idx, r, g, b in color_map:
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_idx,
                    "endRowIndex": row_idx + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 3,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": r, "green": g, "blue": b},
                    }
                },
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

    # ヘッダー行を太字
    for row_idx in (0, 6):
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_idx,
                    "endRowIndex": row_idx + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 3,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                    }
                },
                "fields": "userEnteredFormat.textFormat.bold",
            }
        })

    # ヘッダー行の文字色を白（row 0 のみ）
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": 3,
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                }
            },
            "fields": "userEnteredFormat.textFormat.foregroundColor",
        }
    })

    # 列幅 (A=160, B=160, C=360)
    for col_idx, px in enumerate([160, 160, 360]):
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex": col_idx + 1,
                },
                "properties": {"pixelSize": px},
                "fields": "pixelSize",
            }
        })

    ss.batch_update({"requests": requests})
    print(f"[sheets_updater] 「{_LEGEND_SHEET_NAME}」シート作成・スタイル設定完了")


def _ensure_headers(ws: gspread.Worksheet) -> dict[str, int]:
    """1行目を確認し、_NEW_HEADERS が存在しなければ末尾に追加する。"""
    header_row = ws.row_values(1)

    missing = [h for h in _NEW_HEADERS if h not in header_row]
    if missing:
        required_cols = len(header_row) + len(missing)
        if required_cols > ws.col_count:
            ws.resize(cols=required_cols)
            print(f"[sheets_updater] シート列数を拡張 → {required_cols}列")

    col_map: dict[str, int] = {}
    for hdr in _NEW_HEADERS:
        if hdr in header_row:
            col_map[hdr] = header_row.index(hdr) + 1
        else:
            next_col = len(header_row) + 1
            ws.update_cell(1, next_col, hdr)
            col_map[hdr] = next_col
            header_row.append(hdr)
            print(f"[sheets_updater] ヘッダー追加: 列{next_col} = 「{hdr}」")

    return col_map


def _highlight_row(ws: gspread.Worksheet, row: int,
                   red: float = 211/255, green: float = 211/255, blue: float = 211/255) -> None:
    """指定行全体の背景色を変更する。デフォルトは薄いグレー。"""
    body = {
        "requests": [{
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": row - 1,
                    "endRowIndex": row,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": red, "green": green, "blue": blue}
                    }
                },
                "fields": "userEnteredFormat.backgroundColor",
            }
        }]
    }
    ws.spreadsheet.batch_update(body)


# 背景色プリセット
def _highlight_gray(ws: gspread.Worksheet, row: int) -> None:
    """薄いグレー（投稿済み）"""
    _highlight_row(ws, row, 211/255, 211/255, 211/255)

def _highlight_orange(ws: gspread.Worksheet, row: int) -> None:
    """薄いオレンジ（カニバリスキップ）"""
    _highlight_row(ws, row, 1.0, 0.8, 0.6)

def _highlight_yellow(ws: gspread.Worksheet, row: int) -> None:
    """薄いイエロー（生成待ち）"""
    _highlight_row(ws, row, 1.0, 1.0, 0.6)


def _find_keyword_row(ws: gspread.Worksheet, keyword: str) -> int | None:
    col_a = ws.col_values(1)
    kw = keyword.strip()
    for i, cell in enumerate(col_a):
        if cell.strip() == kw:
            return i + 1
    return None


def _append_to_article_list(
    posted_date: str,
    title: str,
    url: str,
    post_id: int,
    keyword: str,
    related_keywords: list[str],
    sub_keywords: list[str],
    category_name: str,
    tags: list[str],
    char_count: int,
    article_type: str = "",
    kw_status: str = "",
) -> None:
    """「投稿記事一覧」シートに1行追記する。"""
    try:
        ws = _get_or_create_article_list_sheet()
        row = [
            posted_date,
            "",                                  # 公開日（手動更新用）
            title,
            url,
            str(post_id),
            keyword,
            "、".join(related_keywords),
            "、".join(sub_keywords),
            category_name,
            "、".join(tags),
            str(char_count),
            article_type.upper() if article_type else "",  # LONGTAIL / MONETIZE / TREND / FUTURE
            kw_status,                                      # aim / add / now / future / trend
            "下書き",
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"[sheets_updater] 投稿記事一覧に追記: 「{title[:30]}」")
    except Exception as e:
        print(f"[sheets_updater] 投稿記事一覧への追記エラー（続行）: {e}")


def mark_cannibal_results_bulk(
    clusters: list[dict],
) -> None:
    """
    クラスター一覧を受け取り、スプレッドシートに一括書き込みする。
    API呼び出しを最小化するため:
      - ヘッダー取得 × 1回
      - キーワード列（A列）読み込み × 1回
      - セル書き込み × 1回（update_cells でバッチ）
      - 背景色変更 × 1回（batch_update でまとめる）

    clusters の各要素:
      {"main_keyword": str, "related_keywords": [str, ...],
       "skip": bool, "note": str}
    """
    import time

    try:
        ws = _get_worksheet()
        # 新フォーマット（判定列あり）では旧形式列を追加しない
        _header_check = ws.row_values(1)
        if "判定" in _header_check:
            print("[sheets_updater] 新フォーマットシートのため mark_cannibal_results_bulk をスキップ（run_kanikabari_check を使用してください）")
            return
        col_map = _ensure_headers(ws)
        col_a = ws.col_values(1)  # A列（キーワード）を一括取得

        # 投稿ステータス列も一括取得して「投稿済み」行の上書きを防ぐ
        status_col_idx = col_map.get("投稿ステータス")
        if status_col_idx:
            col_status = ws.col_values(status_col_idx)
        else:
            col_status = []

        # keyword → row番号 のマップを構築
        kw_to_row: dict[str, int] = {}
        for i, cell in enumerate(col_a):
            kw_to_row[cell.strip()] = i + 1

        cell_updates: list[gspread.Cell] = []
        color_requests: list[dict] = []

        for c in clusters:
            all_kws = [c["main_keyword"]] + c.get("related_keywords", [])
            is_skip = c.get("skip", False)
            note = c.get("note", "")

            for kw in all_kws:
                row = kw_to_row.get(kw.strip())
                if row is None:
                    continue

                # 投稿済み・要確認行はステータス・色ともに上書きしない
                current_status = col_status[row - 1].strip() if row - 1 < len(col_status) else ""
                if current_status in ("投稿済み", "要確認"):
                    print(f"[sheets_updater] スキップ（保護行）: 行{row} 「{kw}」({current_status})")
                    continue

                if is_skip:
                    cell_updates.append(gspread.Cell(row, col_map["投稿ステータス"], "カニバリスキップ"))
                    if "メモ" in col_map and note:
                        cell_updates.append(gspread.Cell(row, col_map["メモ"], note))
                    r, g, b = 1.0, 0.8, 0.6   # 薄いオレンジ
                    label = "カニバリスキップ"
                else:
                    cell_updates.append(gspread.Cell(row, col_map["投稿ステータス"], "生成待ち"))
                    r, g, b = 1.0, 1.0, 0.6   # 薄いイエロー
                    label = "生成待ち"

                color_requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": row - 1,
                            "endRowIndex": row,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": r, "green": g, "blue": b}
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                })
                print(f"[sheets_updater] {label}: 行{row} 「{kw}」")

        # セル値を一括書き込み
        if cell_updates:
            ws.update_cells(cell_updates, value_input_option="USER_ENTERED")
            time.sleep(1)

        # 背景色を一括変更
        if color_requests:
            ws.spreadsheet.batch_update({"requests": color_requests})

        print(f"[sheets_updater] 一括書き込み完了: {len(cell_updates)}セル / {len(color_requests)}行に背景色適用")

    except Exception as e:
        print(f"[sheets_updater] 一括書き込みエラー（続行）: {e}")


def mark_kanikabari_results_new_format(
    results: list[dict],
    ws: gspread.Worksheet,
) -> None:
    """
    新フォーマットシートにかにばり判定結果を一括書き込みする。

    results の各要素:
        {"keyword": str, "row": int,
         "hantei":    "親KW"|"サブKW"|"カニバリスキップ"|"要確認",
         "togo_saki": str,   # 統合先KW または WP記事タイトル
         "status":   "生成待ち"|"統合対象"|"カニバリスキップ"|"要確認",
         "memo":     str,
         "wp_url":   str,    # 既存WP記事 URL（なければ ""）
         "wp_id":    str,    # 既存WP記事 ID（なければ ""）
        }

    書き込み先列（ヘッダー名で検索、なければ末尾に自動追加）:
        判定 / 統合先KW / ステータス / メモ / 既存記事URL / 既存記事ID

    色凡例:
        生成待ち        = 薄イエロー  (1.0, 1.0, 0.6)
        統合対象        = 薄オレンジ  (1.0, 0.8, 0.6)
        カニバリスキップ = 薄グレー   (0.85, 0.85, 0.85)
        要確認          = 薄ブルー   (0.8, 0.9, 1.0)
    """
    import time

    if not results:
        print("[sheets_updater] かにばり: 書き込み対象なし")
        return

    header_row: list[str] = ws.row_values(1)

    def _find_col(names: list[str]) -> int:
        """複数候補名でヘッダーを検索し、1-based 列番号を返す。なければ -1。"""
        for name in names:
            if name in header_row:
                return header_row.index(name) + 1
        return -1

    def _ensure_col(col_name: str) -> int:
        """列がなければ末尾に追加して 1-based 列番号を返す。"""
        if col_name in header_row:
            return header_row.index(col_name) + 1
        new_col = len(header_row) + 1
        ws.update_cell(1, new_col, col_name)
        header_row.append(col_name)
        time.sleep(0.5)
        return new_col

    c_hantei    = _find_col(["判定"])
    c_togo_saki = _find_col(["統合先KW"])
    c_status    = _find_col(["ステータス"])
    c_memo      = _find_col(["メモ"])
    c_wp_url    = _ensure_col("既存記事URL")
    c_wp_id     = _ensure_col("既存記事ID")

    if c_hantei < 0:
        print("[sheets_updater] かにばり: 「判定」列が見つかりません")
        return

    cell_updates:  list[gspread.Cell] = []
    color_requests: list[dict]        = []

    for r in results:
        row_num   = r["row"]
        hantei    = r.get("hantei",    "")
        togo_saki = r.get("togo_saki", "")
        status    = r.get("status",    "")
        memo      = r.get("memo",      "")
        wp_url    = r.get("wp_url",    "")
        wp_id     = r.get("wp_id",     "")

        if c_hantei    > 0 and hantei:    cell_updates.append(gspread.Cell(row_num, c_hantei,    hantei))
        if c_togo_saki > 0 and togo_saki: cell_updates.append(gspread.Cell(row_num, c_togo_saki, togo_saki))
        if c_status    > 0 and status:    cell_updates.append(gspread.Cell(row_num, c_status,    status))
        if c_memo      > 0 and memo:      cell_updates.append(gspread.Cell(row_num, c_memo,      memo))
        if c_wp_url    > 0 and wp_url:    cell_updates.append(gspread.Cell(row_num, c_wp_url,    wp_url))
        if c_wp_id     > 0 and wp_id:     cell_updates.append(gspread.Cell(row_num, c_wp_id,     wp_id))

        # 背景色
        if status == "生成待ち":
            rc, gc_v, bc = 1.0,   1.0,   0.6    # 薄イエロー
        elif status == "統合対象":
            rc, gc_v, bc = 1.0,   0.8,   0.6    # 薄オレンジ
        elif status == "カニバリスキップ":
            rc, gc_v, bc = 0.85,  0.85,  0.85   # 薄グレー
        elif status == "要確認":
            rc, gc_v, bc = 0.8,   0.9,   1.0    # 薄ブルー
        else:
            rc, gc_v, bc = None, None, None

        if rc is not None:
            color_requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId":       ws.id,
                        "startRowIndex": row_num - 1,
                        "endRowIndex":   row_num,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": rc, "green": gc_v, "blue": bc}
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            })

        print(f"[sheets_updater] {hantei}({status}): 行{row_num} 「{r.get('keyword', '')}」"
              + (f" → WP/{wp_id}" if wp_id else ""))

    if cell_updates:
        ws.update_cells(cell_updates, value_input_option="USER_ENTERED")
        time.sleep(1)

    if color_requests:
        ws.spreadsheet.batch_update({"requests": color_requests})

    print(f"[sheets_updater] かにばり判定書き込み完了: {len(cell_updates)}セル更新 / {len(color_requests)}行に背景色適用")


def mark_posted(
    keyword: str,
    post_id: int,
    post_url: str,
    posted_date: date | None = None,
    sub_keywords: list[str] | None = None,
    article_title: str = "",
    related_keywords: list[str] | None = None,
    category_name: str = "",
    tags: list[str] | None = None,
    char_count: int = 0,
    article_type: str = "",
    kw_status: str = "",
) -> bool:
    """
    スプレッドシートの該当キーワード行に投稿済み情報を書き込み、
    「投稿記事一覧」シートにも1行追記する。
    """
    if posted_date is None:
        posted_date = date.today()
    date_str = posted_date.strftime("%Y/%m/%d")
    sub_keywords = sub_keywords or []
    related_keywords = related_keywords or []
    tags = tags or []

    try:
        ws = _get_worksheet()
        # 新フォーマット（判定列あり）は固定列を使うため _ensure_headers 不要
        _header_check = ws.row_values(1)
        if "判定" in _header_check:
            col_map = {}  # 新フォーマットでは使用しない
        else:
            col_map = _ensure_headers(ws)
        row = _find_keyword_row(ws, keyword)

        if row is None:
            print(f"[sheets_updater] キーワード「{keyword}」が見つかりません（投稿記事一覧には記録）")
            _append_to_article_list(
                posted_date=date_str,
                title=article_title or keyword,
                url=post_url,
                post_id=post_id,
                keyword=keyword,
                related_keywords=related_keywords,
                sub_keywords=sub_keywords,
                category_name=category_name,
                tags=tags,
                char_count=char_count,
                article_type=article_type,
                kw_status=kw_status,
            )
            return False

        header_row = ws.row_values(1)
        is_new_format = "判定" in header_row

        if is_new_format:
            # 新フォーマット: G=ステータス, I=投稿日, J=URL, K=ID（固定列名）
            def _col(name: str) -> int:
                return header_row.index(name) + 1 if name in header_row else -1
            updates = []
            c_status = _col("ステータス")
            c_date   = _col("投稿日")
            c_url    = _col("URL")
            c_id     = _col("ID")
            if c_status > 0: updates.append(gspread.Cell(row, c_status, "投稿済み"))
            if c_date   > 0: updates.append(gspread.Cell(row, c_date,   date_str))
            if c_url    > 0: updates.append(gspread.Cell(row, c_url,    post_url))
            if c_id     > 0: updates.append(gspread.Cell(row, c_id,     str(post_id)))
        else:
            # 旧フォーマット: 動的ヘッダー
            sub_kw_str = "、".join(sub_keywords[:10])
            updates = [
                gspread.Cell(row, col_map["投稿ステータス"], "投稿済み"),
                gspread.Cell(row, col_map["投稿日"],         date_str),
                gspread.Cell(row, col_map["記事URL"],        post_url),
                gspread.Cell(row, col_map["投稿ID"],         str(post_id)),
                gspread.Cell(row, col_map["使用サブKW"],     sub_kw_str),
            ]

        ws.update_cells(updates, value_input_option="USER_ENTERED")
        _highlight_gray(ws, row)

        print(f"[sheets_updater] 書き込み完了: 行{row} 「{keyword}」→ 投稿済み ({date_str}, ID:{post_id}) [背景色適用]")

        # 投稿記事一覧シートに追記
        _append_to_article_list(
            posted_date=date_str,
            title=article_title or keyword,
            url=post_url,
            post_id=post_id,
            keyword=keyword,
            related_keywords=related_keywords,
            sub_keywords=sub_keywords,
            category_name=category_name,
            tags=tags,
            char_count=char_count,
            article_type=article_type,
            kw_status=kw_status,
        )

        return True

    except Exception as e:
        print(f"[sheets_updater] 書き込みエラー（続行）: {e}")
        return False


def mark_duplicate_skip(keyword: str, reason: str = "") -> None:
    """
    記事生成後のタイトル重複スキップをシートに記録する。
    「投稿ステータス」または「ステータス」列に「カニバリスキップ」を書き込み、
    次回の記事生成で同じKWが選ばれないようにする。
    """
    try:
        ws = _get_worksheet()
        headers = ws.row_values(1)

        # ステータス列を検索（投稿ステータス → ステータス の優先順）
        status_col: int | None = None
        for col_name in ["投稿ステータス", "ステータス"]:
            if col_name in headers:
                status_col = headers.index(col_name) + 1  # 1-indexed
                break

        if status_col is None:
            print(f"[sheets_updater] ステータス列が見つからないためスキップ記録不可: {keyword}")
            return

        row = _find_keyword_row(ws, keyword)
        if row is None:
            print(f"[sheets_updater] キーワード「{keyword}」がシートに見つかりません")
            return

        # 投稿済みは上書きしない
        current = ws.cell(row, status_col).value or ""
        if current.strip() == "投稿済み":
            return

        ws.update_cell(row, status_col, "カニバリスキップ")
        _highlight_orange(ws, row)

        # メモ列があれば理由を記録
        if reason and "メモ" in headers:
            memo_col = headers.index("メモ") + 1
            existing_memo = ws.cell(row, memo_col).value or ""
            new_memo = f"重複スキップ: {reason[:60]}"
            if not existing_memo:
                ws.update_cell(row, memo_col, new_memo)

        print(f"[sheets_updater] 重複スキップ記録: 行{row} 「{keyword}」→ カニバリスキップ")

    except Exception as e:
        print(f"[sheets_updater] mark_duplicate_skip エラー: {e}")
