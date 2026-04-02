"""
投稿済みフラグをGoogleスプレッドシートに書き込むモジュール

書き込む列（aim列の右隣から）:
  - 投稿ステータス : 「投稿済み」
  - 投稿日         : YYYY/MM/DD
  - 記事URL        : https://workup-ai.com/slug
  - 投稿ID         : WP post ID
"""
from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials
from datetime import date

from config import GOOGLE_SHEETS_ID, GOOGLE_CREDENTIALS_PATH

# 書き込み権限が必要
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 追加する列ヘッダー（この順番で連続して配置する）
_NEW_HEADERS = ["投稿ステータス", "投稿日", "記事URL", "投稿ID"]

# シングルトン接続キャッシュ
_ws_cache: gspread.Worksheet | None = None


def _get_worksheet() -> gspread.Worksheet:
    global _ws_cache
    if _ws_cache is not None:
        return _ws_cache
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(GOOGLE_SHEETS_ID).get_worksheet(0)
    _ws_cache = ws
    return ws


def _ensure_headers(ws: gspread.Worksheet) -> dict[str, int]:
    """
    1行目を確認し、_NEW_HEADERS が存在しなければ末尾に追加する。
    必要に応じてシートの列数を自動拡張する。

    Returns:
        各ヘッダー名 → 1始まりの列番号 のマップ
    """
    header_row = ws.row_values(1)  # 1行目を取得（1始まり列→リストは0始まり）

    # 必要な最大列数を事前に計算してシートを一括拡張
    missing = [h for h in _NEW_HEADERS if h not in header_row]
    if missing:
        required_cols = len(header_row) + len(missing)
        current_cols = ws.col_count
        if required_cols > current_cols:
            ws.resize(cols=required_cols)
            print(f"[sheets_updater] シート列数を {current_cols} → {required_cols} に拡張")

    col_map: dict[str, int] = {}
    for hdr in _NEW_HEADERS:
        if hdr in header_row:
            col_map[hdr] = header_row.index(hdr) + 1  # 1始まり
        else:
            next_col = len(header_row) + 1
            ws.update_cell(1, next_col, hdr)
            col_map[hdr] = next_col
            header_row.append(hdr)
            print(f"[sheets_updater] ヘッダー追加: 列{next_col} = 「{hdr}」")

    return col_map


def _highlight_row(ws: gspread.Worksheet, row: int) -> None:
    """
    指定行全体の背景色を薄いグレー (RGB: 211, 211, 211) に変更する。
    Sheets API の batchUpdate / repeatCell リクエストを使用。
    """
    # Sheets API は RGB を 0.0〜1.0 の小数で指定
    gray = 211 / 255  # ≈ 0.8274

    body = {
        "requests": [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": row - 1,   # 0始まり
                        "endRowIndex": row,          # exclusive
                        # startColumnIndex / endColumnIndex を省略 → 行全体
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {
                                "red": gray,
                                "green": gray,
                                "blue": gray,
                            }
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
        ]
    }
    ws.spreadsheet.batch_update(body)


def _find_keyword_row(ws: gspread.Worksheet, keyword: str) -> int | None:
    """
    キーワード列（A列）からキーワードを検索し、行番号（1始まり）を返す。
    見つからない場合は None を返す。
    """
    # A列全値を取得（高速）
    col_a = ws.col_values(1)
    kw = keyword.strip()
    for i, cell in enumerate(col_a):
        if cell.strip() == kw:
            return i + 1  # 1始まり
    return None


def mark_posted(
    keyword: str,
    post_id: int,
    post_url: str,
    posted_date: date | None = None,
) -> bool:
    """
    スプレッドシートの該当キーワード行に投稿済み情報を書き込む。

    Args:
        keyword   : キーワード文字列（A列と照合）
        post_id   : WordPress 投稿ID
        post_url  : 記事URL（https://workup-ai.com/slug）
        posted_date: 投稿日（省略時は今日）

    Returns:
        True=書き込み成功 / False=キーワード行が見つからなかった
    """
    if posted_date is None:
        posted_date = date.today()

    date_str = posted_date.strftime("%Y/%m/%d")

    try:
        ws = _get_worksheet()
        col_map = _ensure_headers(ws)
        row = _find_keyword_row(ws, keyword)

        if row is None:
            print(f"[sheets_updater] キーワード「{keyword}」が見つかりません（スキップ）")
            return False

        # バッチ書き込み（API呼び出し1回にまとめる）
        updates = [
            gspread.Cell(row, col_map["投稿ステータス"], "投稿済み"),
            gspread.Cell(row, col_map["投稿日"],         date_str),
            gspread.Cell(row, col_map["記事URL"],        post_url),
            gspread.Cell(row, col_map["投稿ID"],         str(post_id)),
        ]
        ws.update_cells(updates, value_input_option="USER_ENTERED")

        # 行全体をグレーに着色
        _highlight_row(ws, row)

        print(f"[sheets_updater] 書き込み完了: 行{row} 「{keyword}」→ 投稿済み ({date_str}, ID:{post_id}) [背景色適用]")
        return True

    except Exception as e:
        print(f"[sheets_updater] 書き込みエラー（続行）: {e}")
        return False
