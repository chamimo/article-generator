"""
順位下落フラグチェッカー

「順位トラッキング」シートを読み込み、前週比で順位が下落した記事に
「要リライト」フラグと優先度スコアを書き込む。

判定条件:
  - 前週順位が 30 位以内
  - 今週順位が前週より 5 位以上悪化
優先度スコア = 下落幅 × 10

Usage:
    python check_rank_drop.py --site hataraku
    python check_rank_drop.py --site workup-ai --dry-run
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import gspread
from google.oauth2.service_account import Credentials

# ── --site を最初に解析し、config インポート前に ARTICLE_SITE を設定 ──
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument("--site", default="workup-ai")
_pre_args, _ = _pre.parse_known_args()
os.environ["ARTICLE_SITE"] = _pre_args.site

from config import GOOGLE_SHEETS_ID, GOOGLE_CREDENTIALS_PATH

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_TRACKING_SHEET = "順位トラッキング"
_FLAG_HEADER    = "要リライトフラグ"
_SCORE_HEADER   = "優先度スコア"
_RANK_RE        = re.compile(r"^\d+/\d+順位$")

_DROP_THRESHOLD = 5    # 何位以上悪化でフラグ
_RANK_LIMIT     = 30   # 前週何位以内が対象


def _col_letter(n: int) -> str:
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _get_spreadsheet() -> gspread.Spreadsheet:
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=_SCOPES)
    return gspread.authorize(creds).open_by_key(GOOGLE_SHEETS_ID)


def check_rank_drop(dry_run: bool = False) -> None:
    site = os.environ.get("ARTICLE_SITE", "?")
    print(f"[check_rank_drop] サイト: {site}")

    ss = _get_spreadsheet()
    try:
        ws = ss.worksheet(_TRACKING_SHEET)
    except gspread.WorksheetNotFound:
        print(f"[check_rank_drop] ⚠ 「{_TRACKING_SHEET}」シートが見つかりません")
        return

    all_values = ws.get_all_values()
    if not all_values:
        print("[check_rank_drop] シートが空です")
        return

    headers = all_values[0]

    # ── 順位列を特定（"M/D順位" パターン）──
    rank_indices = [i for i, h in enumerate(headers) if _RANK_RE.match(h.strip())]
    if len(rank_indices) < 2:
        print(f"[check_rank_drop] ⚠ 順位列が2列以上必要です（現在 {len(rank_indices)} 列）")
        return

    prev_idx = rank_indices[-2]
    curr_idx = rank_indices[-1]
    print(f"[check_rank_drop] 比較: {headers[prev_idx]} → {headers[curr_idx]}")

    # ── フラグ・スコア列の位置を確認/追加 ──
    if _FLAG_HEADER in headers:
        flag_idx = headers.index(_FLAG_HEADER)
    else:
        flag_idx = len(headers)
        if not dry_run:
            needed = flag_idx + 2
            if ws.col_count < needed:
                ws.resize(rows=ws.row_count, cols=needed + 5)
            ws.update_cell(1, flag_idx + 1, _FLAG_HEADER)
        print(f"[check_rank_drop] 「{_FLAG_HEADER}」列を追加: {_col_letter(flag_idx + 1)}列")

    score_idx = flag_idx + 1
    if not dry_run:
        current_score_header = headers[score_idx] if score_idx < len(headers) else ""
        if current_score_header != _SCORE_HEADER:
            ws.update_cell(1, score_idx + 1, _SCORE_HEADER)
        print(f"[check_rank_drop] 「{_SCORE_HEADER}」列: {_col_letter(score_idx + 1)}列")

    # ── 各行を判定 ──
    def parse_rank(row: list[str], idx: int) -> float | None:
        if idx >= len(row):
            return None
        v = row[idx].strip()
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            return None

    flagged   = []
    batch     = []

    for row_i, row in enumerate(all_values[1:], start=2):
        keyword = row[0].strip() if row else ""
        if not keyword:
            continue

        prev_rank = parse_rank(row, prev_idx)
        curr_rank = parse_rank(row, curr_idx)

        if prev_rank is None or curr_rank is None:
            continue

        drop = curr_rank - prev_rank
        existing_flag = row[flag_idx].strip() if flag_idx < len(row) else ""

        if prev_rank <= _RANK_LIMIT and drop >= _DROP_THRESHOLD:
            score = int(drop * 10)
            flagged.append({
                "keyword":   keyword,
                "prev_rank": prev_rank,
                "curr_rank": curr_rank,
                "drop":      drop,
                "score":     score,
            })
            batch.append({"range": f"{_col_letter(flag_idx + 1)}{row_i}",  "values": [["要リライト"]]})
            batch.append({"range": f"{_col_letter(score_idx + 1)}{row_i}", "values": [[score]]})
        elif existing_flag == "要リライト":
            # 条件を外れた行はフラグをクリア
            batch.append({"range": f"{_col_letter(flag_idx + 1)}{row_i}",  "values": [[""]]})
            batch.append({"range": f"{_col_letter(score_idx + 1)}{row_i}", "values": [[""]]})

    # ── 結果表示 ──
    print(f"\n[check_rank_drop] 要リライト: {len(flagged)} 件")
    for item in sorted(flagged, key=lambda x: -x["score"]):
        print(
            f"  {item['keyword'][:32]:<32} "
            f"{item['prev_rank']:.1f}位 → {item['curr_rank']:.1f}位 "
            f"(▼{item['drop']:.1f}) スコア {item['score']}"
        )

    if dry_run:
        print("\n[dry-run] 書き込みをスキップします")
        return

    if batch:
        BATCH = 500
        for i in range(0, len(batch), BATCH):
            ws.batch_update(batch[i:i + BATCH], value_input_option="RAW")
        print(f"[check_rank_drop] ✅ {len(batch) // 2} 行を更新しました")
    else:
        print("[check_rank_drop] 更新なし")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="順位下落フラグチェック")
    parser.add_argument("--site",    default=os.environ.get("ARTICLE_SITE", "workup-ai"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    check_rank_drop(dry_run=args.dry_run)
