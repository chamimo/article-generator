"""
体験談挿入記事の効果測定ログ

シート: EXPERIENCE｜EffectLog  (blog_config.experience_ss_id 内)
列構成 (A〜M):
  A: blog
  B: post_id
  C: article_url
  D: keyword
  E: inserted_at       (YYYY-MM-DD)
  F: inserted_count
  G: inserted_types    (review,caution,failure 等カンマ区切り)
  H: gsc_clicks_30d
  I: gsc_impressions_30d
  J: ctr_30d           (% 表示)
  K: avg_position_30d
  L: gsc_updated_at    (YYYY-MM-DD HH:MM:SS)
  M: note
"""
from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials

_SHEET_NAME = "EXPERIENCE｜EffectLog"
_SCOPES     = ["https://www.googleapis.com/auth/spreadsheets"]
_HEADER     = [
    "blog", "post_id", "article_url", "keyword",
    "inserted_at", "inserted_count", "inserted_types",
    "gsc_clicks_30d", "gsc_impressions_30d", "ctr_30d",
    "avg_position_30d", "gsc_updated_at", "note",
]


def _open_or_create_sheet(ss_id: str, credentials_path: str):
    """EffectLog シートを開く。なければ自動作成してヘッダーを書く。"""
    creds = Credentials.from_service_account_file(credentials_path, scopes=_SCOPES)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(ss_id)
    try:
        ws = ss.worksheet(_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=_SHEET_NAME, rows=2000, cols=len(_HEADER))
        ws.append_row(_HEADER, value_input_option="USER_ENTERED")
        print(f"[effect_logger] シートを自動作成しました: {_SHEET_NAME}")
        return ws

    existing = ws.get_all_values()
    if not existing or existing[0][:len(_HEADER)] != _HEADER:
        ws.insert_row(_HEADER, index=1, value_input_option="USER_ENTERED")
        print(f"[effect_logger] ヘッダーを補完しました: {_SHEET_NAME}")
    return ws


def log_insertion(
    ss_id: str,
    credentials_path: str,
    blog_name: str,
    post_id: int,
    article_url: str,
    keyword: str,
    inserted_count: int,
    inserted_types: list[str],
    note: str = "",
    dry_run: bool = False,
) -> bool:
    """
    体験談挿入イベントを EffectLog に記録する。

    Returns: True = 書き込み成功（dry_run 時は表示成功）
    """
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    row = [
        blog_name,
        str(post_id),
        article_url,
        keyword,
        today,
        str(inserted_count),
        ",".join(inserted_types),
        "", "", "", "",   # gsc columns (空)
        "",               # gsc_updated_at
        note,
    ]

    if dry_run:
        print(f"[effect_logger] DRY RUN ─ 以下の行を {_SHEET_NAME} に書き込む予定:")
        for col, val in zip(_HEADER, row):
            if val:
                print(f"  {col:<24}: {val}")
        return True

    try:
        ws = _open_or_create_sheet(ss_id, credentials_path)
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"[effect_logger] EffectLog 記録: {blog_name} / {keyword} (post_id={post_id})")
        return True
    except Exception as e:
        print(f"[effect_logger] ⚠️ EffectLog 書き込みエラー: {e}")
        return False


def _fetch_gsc_stats(
    site_url: str,
    page_url: str,
    credentials_path: str,
    days: int = 30,
) -> dict | None:
    """
    指定 URL の GSC データを過去 days 日分で集計して返す。

    Returns: {"clicks": int, "impressions": int, "ctr": float, "position": float}
             or None if no data / error
    """
    from datetime import date, timedelta
    from googleapiclient.discovery import build

    try:
        _GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
        creds = Credentials.from_service_account_file(credentials_path, scopes=_GSC_SCOPES)
        service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

        end_date   = date.today() - timedelta(days=3)
        start_date = end_date - timedelta(days=days - 1)

        normalized_site = (
            site_url if site_url.startswith("sc-domain:")
            else site_url.rstrip("/") + "/"
        )

        resp = service.searchanalytics().query(
            siteUrl=normalized_site,
            body={
                "startDate":  start_date.isoformat(),
                "endDate":    end_date.isoformat(),
                "dimensions": ["page"],
                "dimensionFilterGroups": [{
                    "filters": [{
                        "dimension":  "page",
                        "operator":   "equals",
                        "expression": page_url,
                    }]
                }],
                "rowLimit": 1,
            },
        ).execute()

        rows = resp.get("rows", [])
        if not rows:
            return None

        r = rows[0]
        return {
            "clicks":      int(r.get("clicks",      0)),
            "impressions": int(r.get("impressions", 0)),
            "ctr":         round(r.get("ctr",       0.0) * 100, 2),
            "position":    round(r.get("position",  0.0),       1),
        }
    except Exception as e:
        print(f"[effect_logger] GSC 取得エラー ({page_url}): {e}")
        return None


def update_gsc_data(
    ss_id: str,
    credentials_path: str,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    EffectLog 内の全行に対して GSC 30 日データを更新する。

    対象条件: gsc_updated_at が空、または 7 日以上前の行
    スキップ:  ?p= を含む下書き URL、URL 未設定

    Returns: (updated_count, skipped_count)
    """
    from datetime import datetime, timedelta
    from urllib.parse import urlparse

    try:
        creds = Credentials.from_service_account_file(credentials_path, scopes=_SCOPES)
        gc = gspread.authorize(creds)
        ss = gc.open_by_key(ss_id)

        try:
            ws = ss.worksheet(_SHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            print(f"[effect_logger] {_SHEET_NAME} が存在しません（記事生成後に自動作成されます）")
            return 0, 0

        rows = ws.get_all_values()
        if len(rows) < 2:
            print("[effect_logger] EffectLog: データ行なし")
            return 0, 0

        header = rows[0]
        col_idx = {h: i for i, h in enumerate(header)}

        CI = {k: col_idx.get(k, i) for i, k in enumerate(_HEADER)}

        now             = datetime.now()
        stale_threshold = now - timedelta(days=7)
        updated = skipped = 0

        for sheet_row, row in enumerate(rows[1:], start=2):
            url = row[CI["article_url"]] if len(row) > CI["article_url"] else ""
            gsc_updated = row[CI["gsc_updated_at"]] if len(row) > CI["gsc_updated_at"] else ""

            if not url or "?p=" in url:
                reason = "URL未設定" if not url else "下書きURL"
                print(f"[effect_logger] 行{sheet_row} スキップ（{reason}）: {url or '─'}")
                skipped += 1
                continue

            if gsc_updated:
                try:
                    last_update = datetime.fromisoformat(gsc_updated)
                    if last_update > stale_threshold:
                        skipped += 1
                        continue
                except ValueError:
                    pass

            parsed   = urlparse(url)
            site_url = f"{parsed.scheme}://{parsed.netloc}/"

            if dry_run:
                print(f"[effect_logger] DRY RUN 行{sheet_row}: GSC 取得予定 → {url}")
                stats = _fetch_gsc_stats(site_url, url, credentials_path, days=30)
                if stats:
                    print(f"  clicks={stats['clicks']} impressions={stats['impressions']} "
                          f"ctr={stats['ctr']}% avg_position={stats['position']}")
                else:
                    print("  → GSC データなし（未公開 or データ蓄積前）")
                updated += 1
                continue

            stats = _fetch_gsc_stats(site_url, url, credentials_path, days=30)
            if stats is None:
                print(f"[effect_logger] 行{sheet_row} GSC データなし: {url}")
                skipped += 1
                continue

            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
            ws.update_cell(sheet_row, CI["gsc_clicks_30d"]      + 1, stats["clicks"])
            ws.update_cell(sheet_row, CI["gsc_impressions_30d"] + 1, stats["impressions"])
            ws.update_cell(sheet_row, CI["ctr_30d"]             + 1, stats["ctr"])
            ws.update_cell(sheet_row, CI["avg_position_30d"]    + 1, stats["position"])
            ws.update_cell(sheet_row, CI["gsc_updated_at"]      + 1, timestamp)

            print(f"[effect_logger] 行{sheet_row} GSC 更新: "
                  f"clicks={stats['clicks']} impressions={stats['impressions']} "
                  f"ctr={stats['ctr']}% position={stats['position']}")
            updated += 1

        return updated, skipped

    except Exception as e:
        print(f"[effect_logger] ⚠️ update_gsc_data エラー: {e}")
        raise
