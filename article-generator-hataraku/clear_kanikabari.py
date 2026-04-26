"""
かにばり判定列クリアツール

シートの D列(判定) / E列(統合先KW) / G列(ステータス) / H列(メモ) を空にして
--kanikabari を再実行できる状態に戻す。

Usage:
    python3 clear_kanikabari.py --blog ys-trend
    python3 clear_kanikabari.py --blog hataraku --yes
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

BLOGS_DIR          = Path(__file__).parent / "blogs"
CREDENTIALS_PATH   = Path(__file__).parent / "credentials.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--blog", required=True)
    parser.add_argument("-y", "--yes", action="store_true", help="確認プロンプトをスキップ")
    args = parser.parse_args()

    cfg_path = BLOGS_DIR / args.blog / "blog_config.json"
    if not cfg_path.exists():
        sys.exit(f"blog_config.json が見つかりません: {cfg_path}")

    cfg = json.loads(cfg_path.read_text())
    ss_id  = cfg["candidate_ss_id"]
    sheet  = cfg.get("candidate_sheet", "キーワード")
    name   = cfg.get("display_name", args.blog)

    print(f"対象: {name}  シート: {sheet}  SS_ID: {ss_id}")

    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(CREDENTIALS_PATH), scopes=scopes)
    gc    = gspread.authorize(creds)
    ws    = gc.open_by_key(ss_id).worksheet(sheet)

    rows   = ws.get_all_values()
    header = rows[0] if rows else []

    def col(names: list[str]) -> int:
        for n in names:
            if n in header: return header.index(n)
        return -1

    hantei_idx    = col(["判定"])
    togo_saki_idx = col(["統合先KW"])
    status_idx    = col(["ステータス"])
    memo_idx      = col(["メモ"])

    if hantei_idx < 0:
        sys.exit("「判定」列が見つかりません。")

    # 判定が入っている行を集計
    judged_rows = [
        r for r in range(1, len(rows))
        if 0 <= hantei_idx < len(rows[r]) and rows[r][hantei_idx].strip()
    ]
    print(f"判定済み行数: {len(judged_rows)} 件")
    if not judged_rows:
        print("クリア対象なし。終了します。")
        return

    if not args.yes:
        ans = input(f"{len(judged_rows)} 行の判定をクリアしますか？ [y/N]: ")
        if ans.lower() != "y":
            print("キャンセルしました。")
            return

    # バッチクリア
    clear_cells: list[gspread.Cell] = []
    for row_0based in judged_rows:
        row_1based = row_0based + 1
        for idx in [hantei_idx, togo_saki_idx, status_idx, memo_idx]:
            if idx >= 0:
                clear_cells.append(gspread.Cell(row_1based, idx + 1, ""))

    ws.update_cells(clear_cells, value_input_option="USER_ENTERED")
    print(f"クリア完了: {len(judged_rows)} 行")

    # 背景色もリセット（白）
    color_reqs = []
    for row_0based in judged_rows:
        row_1based = row_0based + 1
        for idx in [hantei_idx, togo_saki_idx, status_idx, memo_idx]:
            if idx < 0: continue
            color_reqs.append({
                "repeatCell": {
                    "range": {
                        "sheetId":          ws.id,
                        "startRowIndex":    row_1based - 1,
                        "endRowIndex":      row_1based,
                        "startColumnIndex": idx,
                        "endColumnIndex":   idx + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            })
        if len(color_reqs) >= 500:
            ws.spreadsheet.batch_update({"requests": color_reqs})
            color_reqs = []
            time.sleep(1)

    if color_reqs:
        ws.spreadsheet.batch_update({"requests": color_reqs})

    print("背景色リセット完了。--kanikabari を再実行できます。")


if __name__ == "__main__":
    main()
