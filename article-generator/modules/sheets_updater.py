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

from config import GOOGLE_SHEETS_ID, GOOGLE_CREDENTIALS_PATH

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
    "文字数（目安）", "アイキャッチURL", "ステータス",
]

_ARTICLE_LIST_SHEET_NAME = "投稿記事一覧"

_ws_cache: gspread.Worksheet | None = None
_ss_cache: gspread.Spreadsheet | None = None


def _get_spreadsheet() -> gspread.Spreadsheet:
    global _ss_cache
    if _ss_cache is not None:
        return _ss_cache
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    _ss_cache = gc.open_by_key(GOOGLE_SHEETS_ID)
    return _ss_cache


def _get_worksheet() -> gspread.Worksheet:
    global _ws_cache
    if _ws_cache is not None:
        return _ws_cache
    _ws_cache = _get_spreadsheet().get_worksheet(0)
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
    eyecatch_url: str,
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
            eyecatch_url,
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
        col_map = _ensure_headers(ws)
        col_a = ws.col_values(1)  # A列を一括取得

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
    eyecatch_url: str = "",
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
        col_map = _ensure_headers(ws)
        row = _find_keyword_row(ws, keyword)

        if row is None:
            print(f"[sheets_updater] キーワード「{keyword}」が見つかりません（スキップ）")
            return False

        sub_kw_str = "、".join(sub_keywords[:10])  # 最大10個
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
            eyecatch_url=eyecatch_url,
        )

        return True

    except Exception as e:
        print(f"[sheets_updater] 書き込みエラー（続行）: {e}")
        return False
