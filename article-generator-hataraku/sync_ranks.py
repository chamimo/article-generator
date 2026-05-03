"""
SEO順位トラッキングスクリプト

Google Search Console API から記事ごとの流入クエリを取得し、
スプレッドシートの「順位トラッキング」シートに書き込む。

シート構成（1行1記事）:
  A: キーワード | B: 記事URL | C: 記事タイトル
  D以降: 4/2順位 | 4/2表示 | 4/2クリック | 4/2CTR | 4/3順位 | ...

対象: 投稿済み記事（キーワードシートの「記事URL」列が入力済みの行）

Usage:
    python sync_ranks.py                   # 最新データを書き込む
    python sync_ranks.py --dry-run         # 書き込みせず確認のみ
    python sync_ranks.py --date 2026-04-03 # 特定日付を指定
    python sync_ranks.py --check-access    # Search Console 接続確認
    python sync_ranks.py --rebuild         # シートを再構築（全列幅・ヘッダーをリセット）
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, timedelta
from html import unescape

import gspread
import requests
from google.oauth2.service_account import Credentials
from requests.auth import HTTPBasicAuth

# ── --site を最初に解析し、config インポート前に ARTICLE_SITE を設定 ──
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--site", default="workup-ai")
_pre_args, _ = _pre.parse_known_args()
os.environ["ARTICLE_SITE"] = _pre_args.site

from config import (
    GOOGLE_SHEETS_ID,
    GOOGLE_CREDENTIALS_PATH,
    SHEETS_KEYWORD_COL,
    WP_URL,
    WP_USERNAME,
    WP_APP_PASSWORD,
    GSC_SITE_URL,
)
from modules.gsc_client import GSCClient

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_TRACKING_SHEET_NAME = "順位トラッキング"
_SOURCE_SHEET_NAME   = "キーワード"
_RESERVED_HEADERS    = {"要リライトフラグ", "優先度スコア"}  # 日付列より後ろに保つ
_URL_COL_HEADER      = "記事URL"
_METRICS             = ["順位"]   # 表示・クリック・CTRは不要のため削除

# 列幅（px）
_COL_WIDTH_KEYWORD = 200
_COL_WIDTH_URL     = 200
_COL_WIDTH_TITLE   = 250
_COL_WIDTH_METRIC  =  80

# 固定列数
_FIXED_COLS = 3   # キーワード / 記事URL / 記事タイトル


# ─────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────

def _col_letter(n: int) -> str:
    """1始まりの列番号 → A, B, ... Z, AA ..."""
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _date_label(d: date) -> str:
    return f"{d.month}/{d.day}"


# ─────────────────────────────────────────────
# WordPress API
# ─────────────────────────────────────────────

def _get_wp_post_info(post_id: int) -> dict | None:
    """投稿IDから permalink・title・status を取得する。"""
    try:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
            auth=HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD),
            params={"_fields": "id,link,title,status"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "link":   data.get("link", ""),
                "title":  unescape(data.get("title", {}).get("rendered", "")),
                "status": data.get("status", ""),
            }
    except Exception:
        pass
    return None


def _extract_post_id(url: str) -> int | None:
    m = re.search(r"[?&]p=(\d+)", url)
    return int(m.group(1)) if m else None


def _resolve_articles(sheet_rows: list[dict]) -> list[dict]:
    """
    キーワードシートの URL記録済み行から、記事情報を解決する。
    ?p=XXXX URL は WP API でパーマリンク・タイトルに変換する。

    Returns:
        [{"keyword": str, "url": str, "title": str, "row": int}, ...]
    """
    resolved = []
    print(f"[sync_ranks] WP API で記事情報を取得中（{len(sheet_rows)}件）...")

    for item in sheet_rows:
        sheet_url = item["url"]
        post_id   = _extract_post_id(sheet_url)

        if post_id:
            info = _get_wp_post_info(post_id)
            if info and "?p=" not in info["link"]:
                resolved.append({
                    "keyword": item["keyword"],
                    "url":     info["link"].rstrip("/") + "/",
                    "title":   info["title"],
                    "row":     item["row"],
                })
                print(f"  ✓ {item['keyword'][:30]} → {info['link']}")
            else:
                print(f"  ⚠ 未解決（下書き?）: {sheet_url}")
        else:
            # すでにパーマリンク形式
            resolved.append({
                "keyword": item["keyword"],
                "url":     sheet_url.rstrip("/") + "/",
                "title":   item.get("title", ""),
                "row":     item["row"],
            })

    return resolved


# ─────────────────────────────────────────────
# Sheets: シート管理
# ─────────────────────────────────────────────

def _get_spreadsheet() -> gspread.Spreadsheet:
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=_SCOPES)
    gc    = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEETS_ID)


def _get_or_create_tracking_sheet(ss: gspread.Spreadsheet) -> gspread.Worksheet:
    """「順位トラッキング」シートを取得または新規作成する。"""
    try:
        return ss.worksheet(_TRACKING_SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=_TRACKING_SHEET_NAME, rows=1000, cols=50)
        print(f"[sync_ranks] 「{_TRACKING_SHEET_NAME}」シートを新規作成しました")
        return ws


def _set_column_widths(ss: gspread.Spreadsheet, ws: gspread.Worksheet,
                       total_metric_cols: int) -> None:
    """列幅を設定する（Google Sheets API batchUpdate）。"""
    sheet_id = ws.id

    requests_body = []

    # 固定3列
    for col_idx, px in enumerate([_COL_WIDTH_KEYWORD, _COL_WIDTH_URL, _COL_WIDTH_TITLE]):
        requests_body.append({
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

    # メトリクス列（4列ずつ）
    if total_metric_cols > 0:
        requests_body.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": _FIXED_COLS,
                    "endIndex": _FIXED_COLS + total_metric_cols,
                },
                "properties": {"pixelSize": _COL_WIDTH_METRIC},
                "fields": "pixelSize",
            }
        })

    if requests_body:
        ss.batch_update({"requests": requests_body})


def _freeze_header(ss: gspread.Spreadsheet, ws: gspread.Worksheet) -> None:
    """1行目と3列目までを固定する。"""
    ss.batch_update({"requests": [{
        "updateSheetProperties": {
            "properties": {
                "sheetId": ws.id,
                "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": _FIXED_COLS},
            },
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        }
    }]})


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────

def sync_ranks(target_date: date | None = None, dry_run: bool = False,
               rebuild: bool = False) -> None:

    # ── 1. GSC データ取得 ──
    client = GSCClient(site_url=GSC_SITE_URL)

    if target_date is None:
        print("[sync_ranks] データが存在する最新日付を検索中...")
        target_date = client.find_latest_date_with_data()
        if target_date is None:
            print("[sync_ranks] ⚠ Search Console にデータがありません。")
            sys.exit(1)

    date_label = _date_label(target_date)
    print(f"[sync_ranks] 取得日: {target_date} ({date_label})")

    try:
        page_query_data = client.get_page_query_data(target_date=target_date)
    except Exception as e:
        print(f"[sync_ranks] Search Console API エラー: {e}")
        sys.exit(1)

    total_rows = sum(len(v) for v in page_query_data.values())
    print(f"[sync_ranks] GSC データ: {len(page_query_data)}ページ / {total_rows}クエリ")

    # ── 2. キーワードシートから投稿済み記事を読み込む ──
    ss         = _get_spreadsheet()
    source_ws  = ss.worksheet(_SOURCE_SHEET_NAME)
    all_values = source_ws.get_all_values()
    headers    = all_values[0]

    kw_idx  = next((i for i, h in enumerate(headers) if h.strip() == SHEETS_KEYWORD_COL), 0)
    url_idx = next((i for i, h in enumerate(headers) if h.strip() == _URL_COL_HEADER), None)

    if url_idx is None:
        print(f"[sync_ranks] ⚠ 「{_URL_COL_HEADER}」列が見つかりません。")
        return

    sheet_rows = [
        {"keyword": row[kw_idx].strip(), "url": row[url_idx].strip(), "row": row_i}
        for row_i, row in enumerate(all_values[1:], start=2)
        if row[kw_idx].strip() and url_idx < len(row) and row[url_idx].strip()
    ]
    print(f"[sync_ranks] 投稿済みキーワード（URL記録あり）: {len(sheet_rows)}件")

    if not sheet_rows:
        print("[sync_ranks] 書き込む記事がありません。")
        return

    # ── 3. WP API で permalink・title を解決 ──
    articles = _resolve_articles(sheet_rows)
    print(f"[sync_ranks] 解決済み: {len(articles)}件")

    if not articles:
        print("[sync_ranks] 解決できた記事がありません。")
        return

    # ── 4. 順位トラッキングシートを取得・初期化 ──
    ws = _get_or_create_tracking_sheet(ss)

    if rebuild:
        ws.clear()
        print("[sync_ranks] シートをクリアしました（--rebuild）")

    tracking_values = ws.get_all_values()
    tracking_headers = tracking_values[0] if tracking_values else []

    # ── 5. ヘッダー行を確認・初期化 ──
    base_headers = ["キーワード", "記事URL", "記事タイトル"]
    if not tracking_headers:
        if not dry_run:
            ws.update(values=[base_headers], range_name="A1:C1")
        tracking_headers = base_headers
        print("[sync_ranks] ヘッダー行を初期化しました")

    # 今日の日付列を確認・追加
    expected_metric_headers = [f"{date_label}{m}" for m in _METRICS]
    if expected_metric_headers[0] in tracking_headers:
        base_col_idx = tracking_headers.index(expected_metric_headers[0])
        print(f"[sync_ranks] 既存の日付列を使用: 列{base_col_idx+1} ({date_label})")
    else:
        # フラグ列より前に挿入する位置を探す
        reserved_start = next(
            (i for i, h in enumerate(tracking_headers) if h in _RESERVED_HEADERS),
            len(tracking_headers),
        )
        base_col_idx = reserved_start
        if not dry_run:
            if reserved_start < len(tracking_headers):
                # フラグ列が既にある → insertDimension で列を押し込む
                ss.batch_update({"requests": [{
                    "insertDimension": {
                        "range": {
                            "sheetId":    ws.id,
                            "dimension":  "COLUMNS",
                            "startIndex": reserved_start,
                            "endIndex":   reserved_start + len(_METRICS),
                        },
                        "inheritFromBefore": True,
                    }
                }]})
            else:
                # フラグ列なし → 末尾に追加（列数拡張）
                needed = base_col_idx + len(_METRICS)
                if ws.col_count < needed:
                    ws.resize(rows=ws.row_count, cols=needed + 20)
            # ヘッダー書き込み
            for i, h in enumerate(expected_metric_headers):
                ws.update_cell(1, base_col_idx + 1 + i, h)
            tracking_headers = ws.row_values(1)
        else:
            tracking_headers = tracking_headers + expected_metric_headers
        print(f"[sync_ranks] 新しい日付列を追加: 列{base_col_idx+1}〜{base_col_idx+4} ({date_label})")

    # ── 6. 既存行のキーワード → 行番号マッピング ──
    # tracking_values を再取得（ヘッダー追加後）
    if not dry_run:
        tracking_values = ws.get_all_values()

    kw_to_tracking_row: dict[str, int] = {}
    for row_i, row in enumerate(tracking_values[1:], start=2):
        if row and row[0].strip():
            kw_to_tracking_row[row[0].strip()] = row_i

    # ── 7. 各記事の GSC データを収集して書き込み ──
    updates:  list[dict] = []
    new_rows: list[list] = []
    matched  = 0
    no_data  = []

    for art in articles:
        keyword = art["keyword"]
        url     = art["url"]
        title   = art["title"]

        # GSC データ取得（末尾スラッシュの有無を両方試す）
        url_slash   = url.rstrip("/") + "/"
        url_noslash = url.rstrip("/")
        page_queries = page_query_data.get(url_slash) or page_query_data.get(url_noslash) or []
        best         = client.find_best_query(keyword, page_queries) if page_queries else None

        if keyword in kw_to_tracking_row:
            # 既存行の更新
            tracking_row = kw_to_tracking_row[keyword]

            # URL・タイトルを更新（空の場合のみ）
            if not dry_run:
                existing_row = tracking_values[tracking_row - 1] if tracking_row - 1 < len(tracking_values) else []
                if len(existing_row) < 2 or not existing_row[1]:
                    updates.append({"range": f"B{tracking_row}", "values": [[url]]})
                if len(existing_row) < 3 or not existing_row[2]:
                    updates.append({"range": f"C{tracking_row}", "values": [[title]]})

        else:
            # 新規行追加
            new_row = [keyword, url, title] + [""] * (base_col_idx - _FIXED_COLS)
            new_rows.append({"row_data": new_row, "keyword": keyword, "url": url})

        # 順位データを書き込み
        if best:
            position = round(best["position"], 1)
            values   = [position]
            matched += 1
            print(f"  ✓ {keyword[:28]} → {best['query']} | {position}位")

            if keyword in kw_to_tracking_row:
                tracking_row = kw_to_tracking_row[keyword]
                for i, val in enumerate(values):
                    updates.append({
                        "range":  f"{_col_letter(base_col_idx + 1 + i)}{tracking_row}",
                        "values": [[val]],
                    })
            else:
                # 新規行のメトリクスは後で追加
                for nr in new_rows:
                    if nr["keyword"] == keyword:
                        nr["metrics"] = values
                        break
        else:
            no_data.append(keyword)

    print(f"\n[sync_ranks] GSCマッチ: {matched}件 / データなし: {len(no_data)}件")
    if no_data:
        print("  ※ データなしの主な原因:")
        print("     - 新規投稿記事（Googleインデックスまで数週間かかる場合あり）")
        print("     - GSCデータの遅延（約2〜3日）")
        print("     - 検索順位が圏外または表示回数ゼロ")
        for kw in no_data[:10]:
            print(f"     - {kw[:50]}")
        if len(no_data) > 10:
            print(f"     ... 他{len(no_data) - 10}件")
    existing_updated = len(set(a["keyword"] for a in articles) & set(kw_to_tracking_row.keys()))
    print(f"[sync_ranks] 新規行: {len(new_rows)}件 / 既存行更新: {existing_updated}件")

    if dry_run:
        print("\n[dry-run] 書き込みをスキップします。")
        print("書き込み予定:")
        print(f"  新規行 {len(new_rows)}件:")
        for nr in new_rows[:5]:
            print(f"    - {nr['keyword'][:40]} | {nr['url']}")
        return

    # ── 8. 新規行を追記 ──
    if new_rows:
        # 既存データの末尾行を取得
        existing_count = len([r for r in tracking_values[1:] if r and r[0].strip()])
        next_row = existing_count + 2  # 1行目はヘッダー

        for nr in new_rows:
            row_data = nr["row_data"]
            # メトリクスを正しい列に配置
            metrics = nr.get("metrics", [])
            if metrics:
                # base_col_idx の位置に挿入（0-indexed）
                while len(row_data) < base_col_idx:
                    row_data.append("")
                row_data.extend(metrics)

            ws.update(
                values=[row_data],
                range_name=f"A{next_row}:{_col_letter(len(row_data))}{next_row}",
            )
            # マッピングを更新
            kw_to_tracking_row[nr["keyword"]] = next_row
            next_row += 1

    # ── 9. バッチ更新（既存行のメトリクス・URL・タイトル）──
    if updates:
        BATCH = 1000
        for i in range(0, len(updates), BATCH):
            ws.batch_update(updates[i:i + BATCH], value_input_option="RAW")

    # ── 10. 列幅・ヘッダー固定 ──
    total_metric_cols = len(tracking_headers) - _FIXED_COLS + len(_METRICS)
    _set_column_widths(ss, ws, total_metric_cols)
    _freeze_header(ss, ws)

    total_written = len(new_rows) + len([u for u in updates if "順位" in u.get("range", "") or _col_letter(base_col_idx + 1) in u.get("range", "")])
    print(f"\n[sync_ranks] ✅ 「{_TRACKING_SHEET_NAME}」シートに書き込みました。")
    print(f"  新規行: {len(new_rows)}件 / 更新: {len(updates)}セル / GSCマッチ: {matched}件")


# ─────────────────────────────────────────────
# 接続確認
# ─────────────────────────────────────────────

def check_access() -> None:
    import json
    from googleapiclient.errors import HttpError

    with open(GOOGLE_CREDENTIALS_PATH) as f:
        cred_data = json.load(f)
    print(f"[check] サービスアカウント: {cred_data.get('client_email','')}")

    client = GSCClient(site_url=GSC_SITE_URL)
    print(f"[check] 対象サイト: {client.site_url}")
    try:
        service   = client._get_service()
        sites     = service.sites().list().execute()
        site_list = [s["siteUrl"] for s in sites.get("siteEntry", [])]
        print(f"[check] アクセス可能なサイト: {site_list}")

        d    = client.find_latest_date_with_data() or (date.today() - timedelta(days=3))
        resp = service.searchanalytics().query(
            siteUrl=client.site_url,
            body={
                "startDate":  d.isoformat(),
                "endDate":    d.isoformat(),
                "dimensions": ["query"],
                "rowLimit":   5,
            },
        ).execute()
        rows = resp.get("rows", [])
        print(f"\n[check] ✅ 接続成功！ テストクエリ ({d}): {len(rows)}件取得")
        for r in rows:
            print(f"  - {r['keys'][0]}: {r['position']:.1f}位 / 表示{r['impressions']} / クリック{r['clicks']}")

    except HttpError as e:
        print(f"\n❌ エラー: {e}")
    except Exception as e:
        print(f"\n❌ エラー: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GSC順位データを順位トラッキングシートに同期")
    parser.add_argument("--site",         default=os.environ.get("ARTICLE_SITE", "workup-ai"),
                        help="対象サイト名 (sites/<site>/config.py を使用)")
    parser.add_argument("--dry-run",      action="store_true",  help="書き込みせず確認のみ")
    parser.add_argument("--check-access", action="store_true",  help="Search Console 接続確認")
    parser.add_argument("--rebuild",      action="store_true",  help="シートをクリアして再構築")
    parser.add_argument("--date",         type=str, default=None, help="対象日付 (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.check_access:
        check_access()
    else:
        target = date.fromisoformat(args.date) if args.date else None
        sync_ranks(target_date=target, dry_run=args.dry_run, rebuild=args.rebuild)
