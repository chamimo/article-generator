"""
ref_url_fetcher.py

キーワードシートの各キーワードに対して参考URLを自動取得・書き込みするモジュール。

追加列:
  - 参考WEB①  : DuckDuckGo検索の上位1件URL（日本語）
  - 参考WEB②  : DuckDuckGo検索の上位2件目URL
  - 参考WEB③  : DuckDuckGo検索の上位3件目URL

使い方:
  python modules/ref_url_fetcher.py --blog workup-ai
  python modules/ref_url_fetcher.py --all
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

log = logging.getLogger(__name__)

# ── ブログ一覧（name, ss_id） ────────────────────────────
BLOGS = [
    ("hataraku",       "1w0oAjA8JflYqHZP31XeF2RYZ_jxdznRl6D2e8387jLU"),
    ("workup-ai",      "13f8HorKWHGKYpFF5svHF4Cxj5drZ2OKK39FamaVY9n4"),
    ("hapipo8",        "1Mz5yztHfu8gnQ6JaPau47daK0Y4ykogTKNWyPtdDGrM"),
    ("hida-no-omoide", "16DZ0M_EbviPRhZBNwV_FpEJL2SjsuZw9BLKwAJE9AWE"),
    ("web-study1",     "1fyJCqT5Ohqb6OgY2w6LxAVydeuXuD6CdMweh1w1zMAM"),
    ("kaerudoko",      "16h7aV0iHC8dsQR05xMeKTqUvMSXb2lGcNfxr6P6lp8I"),
    ("ys-trend",       "1PPkCm-QEK-H9SSsAJiFksKhNl3IyDk495--xmChSGRM"),
]

COL_WEB1 = "参考WEB①"
COL_WEB2 = "参考WEB②"
COL_WEB3 = "参考WEB③"
ALL_COLS  = [COL_WEB1, COL_WEB2, COL_WEB3]

# ── 検索ユーティリティ ───────────────────────────────────

def _search_web(keyword: str) -> list[str]:
    """DuckDuckGo（ddgs）で上位3件のURLを返す。失敗時は空リスト。"""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(keyword, region="jp-jp", max_results=3))
        return [r.get("href", "") for r in results if r.get("href")]
    except Exception as e:
        log.warning(f"[ref_url] WEB検索エラー ({keyword}): {e}")
    return []


# ── スプレッドシート操作 ─────────────────────────────────

def _ensure_columns(ws, header: list[str]) -> tuple[int, int, int]:
    """
    参考WEB①②③列が存在しなければ末尾に追加し、列番号（1-indexed）を返す。
    """
    from gspread.utils import rowcol_to_a1

    def _get_or_add(col_name: str) -> int:
        if col_name in header:
            return header.index(col_name) + 1
        new_col = len(header) + 1
        ws.update_cell(1, new_col, col_name)
        header.append(col_name)
        log.info(f"[ref_url] 列追加: {col_name} → {rowcol_to_a1(1, new_col)}")
        return new_col

    col1 = _get_or_add(COL_WEB1)
    col2 = _get_or_add(COL_WEB2)
    col3 = _get_or_add(COL_WEB3)
    return col1, col2, col3


def process_sheet(name: str, ss_id: str, dry_run: bool = False, limit: int = 0) -> None:
    """
    指定ブログのキーワードシートを処理する。
    空欄のURLのみ取得して書き込む（入力済みはスキップ）。

    limit: 0=全件, N=先頭N件のみ（テスト用）
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        log.error("gspread が未インストールです")
        return

    import os
    project_root = os.path.join(os.path.dirname(__file__), "..")
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from config import GOOGLE_CREDENTIALS_PATH

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)

    try:
        ws = gc.open_by_key(ss_id).worksheet("キーワード")
    except Exception as e:
        log.error(f"[ref_url] {name}: シート接続エラー: {e}")
        return

    all_values = ws.get_all_values()
    if not all_values:
        log.warning(f"[ref_url] {name}: シートが空です")
        return

    header = list(all_values[0])
    col1, col2, col3 = _ensure_columns(ws, header)
    cols = [col1, col2, col3]

    kw_col = 0  # A列（キーワード）

    # 処理行リストを収集 — 3列のいずれかが空の行のみ対象
    tasks: list[tuple[int, str, list[str]]] = []  # (row_1indexed, keyword, [cur1, cur2, cur3])
    for i, row in enumerate(all_values[1:], start=2):
        kw = row[kw_col].strip() if len(row) > kw_col else ""
        if not kw:
            continue

        cur = [row[c - 1].strip() if len(row) >= c else "" for c in cols]

        if all(cur):  # 3列すべて埋まっていればスキップ
            continue

        tasks.append((i, kw, cur))

    if limit:
        tasks = tasks[:limit]

    print(f"[ref_url] {name}: {len(tasks)}件を処理します（dry_run={dry_run}）")

    updated = 0
    for row_idx, kw, cur in tasks:
        # 不足している件数だけ追加で取得する
        n_missing = sum(1 for c in cur if not c)
        fetched = _search_web(kw) if n_missing else []
        time.sleep(0.5)  # レート制限対策

        # 既存値を活かしつつ、空欄を fetched で順番に埋める
        fetch_iter = iter(fetched)
        new_vals = [c if c else next(fetch_iter, "") for c in cur]

        if dry_run:
            print(f"  [{row_idx}] {kw[:30]:<30} | ①{new_vals[0][:40]} | ②{new_vals[1][:40]} | ③{new_vals[2][:40]}")
            continue

        updates: list[dict] = []
        for idx, (old, new, col) in enumerate(zip(cur, new_vals, cols)):
            if new and not old:
                updates.append({"range": f"{_col_letter(col)}{row_idx}", "values": [[new]]})

        if updates:
            ws.batch_update(updates)
            updated += 1
            print(f"  [{row_idx}] {kw[:30]:<30} ✓ ({len(updates)}列書き込み)")

        time.sleep(0.2)

    print(f"[ref_url] {name}: 完了 ({updated}件書き込み)")


def _col_letter(col_1indexed: int) -> str:
    """列番号（1-indexed）をA1形式のアルファベットに変換する。"""
    result = ""
    while col_1indexed:
        col_1indexed, rem = divmod(col_1indexed - 1, 26)
        result = chr(65 + rem) + result
    return result


# ── CLI エントリポイント ─────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="キーワードシートに参考URLを自動入力する")
    parser.add_argument("--blog", help="対象ブログ名（例: workup-ai）")
    parser.add_argument("--all",  action="store_true", help="全ブログを処理する")
    parser.add_argument("--dry-run", action="store_true", help="書き込みせず結果を表示のみ")
    parser.add_argument("--limit", type=int, default=0, help="処理件数上限（テスト用）")
    args = parser.parse_args()

    if args.all:
        targets = BLOGS
    elif args.blog:
        targets = [(n, s) for n, s in BLOGS if n == args.blog]
        if not targets:
            print(f"ブログ名 '{args.blog}' が見つかりません。利用可能: {[n for n,_ in BLOGS]}")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)

    for name, ss_id in targets:
        print(f"\n{'='*50}")
        print(f"処理中: {name}")
        print(f"{'='*50}")
        process_sheet(name, ss_id, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
