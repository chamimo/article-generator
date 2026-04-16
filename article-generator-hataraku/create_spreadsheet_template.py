"""
新ブログ用スプレッドシート雛形作成スクリプト

workup-ai の構成を複製して、空の雛形スプレッドシートを作成する。

Usage:
    python3 create_spreadsheet_template.py --title "新ブログ_AIM判定まとめ"
"""
import argparse
import os
import sys

os.environ.setdefault("ARTICLE_SITE", "workup-ai")

from config import GOOGLE_CREDENTIALS_PATH
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_clients():
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    service = build("sheets", "v4", credentials=creds)
    return gc, service


# ─────────────────────────────────────────────
# 色定義（RGBA 0-1）
# ─────────────────────────────────────────────
def _rgb(r, g, b):
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


HEADER_BG   = _rgb(67, 133, 245)   # 青: ヘッダー行
HEADER_FG   = {"red": 1, "green": 1, "blue": 1}  # 白文字

YELLOW_BG   = _rgb(255, 255, 153)  # 薄いイエロー: 生成待ち
GRAY_BG     = _rgb(204, 204, 204)  # 薄いグレー:   投稿済み
ORANGE_BG   = _rgb(255, 204, 153)  # 薄いオレンジ: カニバリスキップ


# ─────────────────────────────────────────────
# シート1: キーワード
# ─────────────────────────────────────────────
KW_HEADERS = [
    "キーワード", "SEO難易度", "月間検索数", "CPC（$）", "競合性",
    "キーワード", "allintitle", "intitle", "Q&Aサイト", "",
    "無料ブログ", "", "TikTok", "", "Instagram", "", "エックス", "",
    "Facebook", "", "aim", "投稿ステータス", "投稿日", "記事URL",
    "投稿ID", "使用サブKW", "メモ",
]

# 列幅 (列インデックス0始まり → ピクセル)
KW_COL_WIDTHS = {
    0: 250,   # キーワード
    1: 80,    # SEO難易度
    2: 90,    # 月間検索数
    3: 70,    # CPC
    4: 60,    # 競合性
    5: 200,   # キーワード(2)
    6: 80,    # allintitle
    7: 70,    # intitle
    20: 50,   # aim
    21: 90,   # 投稿ステータス
    22: 80,   # 投稿日
    23: 220,  # 記事URL
    24: 70,   # 投稿ID
    25: 300,  # 使用サブKW
    26: 200,  # メモ
}


# ─────────────────────────────────────────────
# シート2: 投稿記事一覧
# ─────────────────────────────────────────────
ARTICLE_HEADERS = [
    "投稿日", "公開日", "記事タイトル", "URL", "WP投稿ID",
    "メインKW", "関連KW", "使用サブKW", "カテゴリー", "タグ",
    "文字数（目安）", "アイキャッチURL", "ステータス",
]

ARTICLE_COL_WIDTHS = {
    0: 90,   # 投稿日
    1: 90,   # 公開日
    2: 300,  # 記事タイトル
    3: 250,  # URL
    4: 80,   # WP投稿ID
    5: 200,  # メインKW
    6: 250,  # 関連KW
    7: 250,  # 使用サブKW
    8: 150,  # カテゴリー
    9: 200,  # タグ
    10: 90,  # 文字数
    11: 250, # アイキャッチURL
    12: 80,  # ステータス
}


# ─────────────────────────────────────────────
# シート3: 凡例
# ─────────────────────────────────────────────
LEGEND_ROWS = [
    ["背景色", "ステータス", "説明"],
    ["白（デフォルト）", "未処理", "まだAIM判定されていないキーワード"],
    ["薄いイエロー", "生成待ち", "AIM判定済み・記事生成待ち"],
    ["薄いグレー", "投稿済み", "記事生成・WP投稿完了"],
    ["薄いオレンジ", "カニバリスキップ", "既存記事と内容が重複するためスキップ"],
    [],
    ["追加情報", "", ""],
    ["キーワード列", "メインキーワード", ""],
    ["AIM列", "「aim」と入力するとシステムが処理対象として認識", ""],
    ["メモ列", "カニバリ理由・差別化メモが自動記入される", ""],
    ["投稿日・URL・ID", "投稿後に自動記入される", ""],
]

LEGEND_COLOR_ROWS = {
    1: None,           # ヘッダー (HEADER_BG)
    2: None,           # 白
    3: YELLOW_BG,      # 生成待ち
    4: GRAY_BG,        # 投稿済み
    5: ORANGE_BG,      # カニバリスキップ
}


# ─────────────────────────────────────────────
# シート4: 順位トラッキング
# ─────────────────────────────────────────────
TRACKING_HEADERS = ["キーワード", "記事URL", "記事タイトル"]

TRACKING_COL_WIDTHS = {
    0: 200,  # キーワード
    1: 200,  # 記事URL
    2: 250,  # 記事タイトル
}


# ─────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────
def _sheet_id(ws):
    return ws._properties["sheetId"]


def _set_col_widths(service, spreadsheet_id, sheet_id, widths: dict):
    requests = []
    for col_idx, px in widths.items():
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
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()


def _freeze(service, spreadsheet_id, sheet_id, rows=1, cols=0):
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": rows, "frozenColumnCount": cols},
                },
                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
            }
        }]},
    ).execute()


def _format_header_row(service, spreadsheet_id, sheet_id, n_cols):
    """1行目を青背景・白太字に。"""
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": n_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": HEADER_BG,
                        "textFormat": {"foregroundColor": HEADER_FG, "bold": True},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        }]},
    ).execute()


def _color_cell(service, spreadsheet_id, sheet_id, row_idx, n_cols, color):
    """指定行に背景色を塗る（0始まりrow_idx）。"""
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_idx,
                    "endRowIndex": row_idx + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": n_cols,
                },
                "cell": {
                    "userEnteredFormat": {"backgroundColor": color}
                },
                "fields": "userEnteredFormat.backgroundColor",
            }
        }]},
    ).execute()


# ─────────────────────────────────────────────
# メイン作成処理
# ─────────────────────────────────────────────
def create_template(title: str, spreadsheet_id: str | None = None) -> str:
    gc, service = _get_clients()

    if not spreadsheet_id:
        raise ValueError("--id でスプレッドシートIDを指定してください")

    print(f"[create] スプレッドシートに接続: {spreadsheet_id}")
    ss = gc.open_by_key(spreadsheet_id)
    print(f"[create] 接続OK: 「{ss.title}」")

    # ── シート1: キーワード ──────────────────────
    print("[create] シート「キーワード」を設定中...")
    kw_ws = ss.get_worksheet(0)
    kw_ws.resize(rows=1000, cols=len(KW_HEADERS))
    kw_ws.update(values=[KW_HEADERS], range_name="A1")
    sid = _sheet_id(kw_ws)
    _format_header_row(service, spreadsheet_id, sid, len(KW_HEADERS))
    _freeze(service, spreadsheet_id, sid, rows=1, cols=1)
    _set_col_widths(service, spreadsheet_id, sid, KW_COL_WIDTHS)

    # ── シート2: 投稿記事一覧 ────────────────────
    print("[create] シート「投稿記事一覧」を設定中...")
    art_ws = ss.add_worksheet(title="投稿記事一覧", rows=1000, cols=len(ARTICLE_HEADERS))
    art_ws.update(values=[ARTICLE_HEADERS], range_name="A1")
    sid = _sheet_id(art_ws)
    _format_header_row(service, spreadsheet_id, sid, len(ARTICLE_HEADERS))
    _freeze(service, spreadsheet_id, sid, rows=1, cols=0)
    _set_col_widths(service, spreadsheet_id, sid, ARTICLE_COL_WIDTHS)

    # ── シート3: 凡例 ─────────────────────────────
    print("[create] シート「凡例」を設定中...")
    leg_ws = ss.add_worksheet(title="凡例", rows=30, cols=5)
    leg_ws.update(values=LEGEND_ROWS, range_name="A1")
    sid = _sheet_id(leg_ws)
    # ヘッダー行 (1行目)
    _format_header_row(service, spreadsheet_id, sid, 3)
    # 色行
    _color_cell(service, spreadsheet_id, sid, 2, 3, YELLOW_BG)   # 生成待ち (3行目)
    _color_cell(service, spreadsheet_id, sid, 3, 3, GRAY_BG)     # 投稿済み (4行目)
    _color_cell(service, spreadsheet_id, sid, 4, 3, ORANGE_BG)   # カニバリ (5行目)
    _set_col_widths(service, spreadsheet_id, sid, {0: 150, 1: 250, 2: 350})

    # ── シート4: 順位トラッキング ─────────────────
    print("[create] シート「順位トラッキング」を設定中...")
    trk_ws = ss.add_worksheet(title="順位トラッキング", rows=1000, cols=50)
    trk_ws.update(values=[TRACKING_HEADERS], range_name="A1")
    sid = _sheet_id(trk_ws)
    _format_header_row(service, spreadsheet_id, sid, len(TRACKING_HEADERS))
    _freeze(service, spreadsheet_id, sid, rows=1, cols=3)
    _set_col_widths(service, spreadsheet_id, sid, TRACKING_COL_WIDTHS)

    # ── 共有設定: サービスアカウントが所有者 → 誰でも閲覧可 (任意) ──
    # 不要であればコメントアウト
    # gc.insert_permission(spreadsheet_id, None, perm_type='anyone', role='writer')

    print(f"\n[create] ✅ 完了！")
    print(f"  スプレッドシート名: {title}")
    print(f"  ID: {spreadsheet_id}")
    print(f"  URL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")
    return spreadsheet_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="新ブログ用スプレッドシート雛形を作成")
    parser.add_argument("--title", default="新ブログ_AIM判定まとめ",
                        help="スプレッドシートのタイトル（ログ表示用）")
    parser.add_argument("--id", required=True, dest="sheet_id",
                        help="事前に作成・共有済みのスプレッドシートID")
    args = parser.parse_args()
    create_template(args.title, args.sheet_id)
