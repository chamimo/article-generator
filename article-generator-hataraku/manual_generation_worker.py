#!/usr/bin/env python3
"""
Spreadsheet queue worker for manual article generation.

GAS writes requests to the "手動実行" sheet. This worker picks rows whose
ステータス is "未実行" and runs the existing run_daily.sh wrapper.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_SPREADSHEET_ID = "1_pgNf2-JNlT2uwJFGzlVPGpuVpj2mf5eSsa_YLwMwGc"
DEFAULT_QUEUE_SHEET = "手動実行"
DEFAULT_PROJECT_DIR = Path("/Users/yama/article-generator-hataraku")
DEFAULT_CREDENTIALS = DEFAULT_PROJECT_DIR / "credentials.json"
LOCK_STALE_SECONDS = 60 * 60 * 6


HEADERS = {
    "id": "リクエストID",
    "requested_at": "依頼日時",
    "blog": "ブログ",
    "count": "記事数",
    "status": "ステータス",
    "memo": "メモ",
    "started_at": "実行開始",
    "finished_at": "実行終了",
}


def now_jst() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_sheet(spreadsheet_id: str, sheet_name: str, credentials_path: Path):
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(credentials_path), scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id).worksheet(sheet_name)


def header_map(values: list[list[str]]) -> dict[str, int]:
    if not values:
        raise RuntimeError("手動実行シートが空です。先にGASボタンで依頼を追加してください。")
    headers = [str(v).strip() for v in values[0]]
    missing = [name for name in HEADERS.values() if name not in headers]
    if missing:
        raise RuntimeError(f"手動実行シートに必要な見出しがありません: {missing}")
    return {name: headers.index(name) + 1 for name in HEADERS.values()}


def cell(row: list[str], col_1based: int) -> str:
    idx = col_1based - 1
    return str(row[idx]).strip() if 0 <= idx < len(row) else ""


def update_status(ws, cols: dict[str, int], row_number: int, status: str, memo: str = "", started: str = "", finished: str = ""):
    updates = [
        {"range": f"{_col_letter(cols[HEADERS['status']])}{row_number}", "values": [[status]]},
    ]
    if memo:
        updates.append({"range": f"{_col_letter(cols[HEADERS['memo']])}{row_number}", "values": [[memo]]})
    if started:
        updates.append({"range": f"{_col_letter(cols[HEADERS['started_at']])}{row_number}", "values": [[started]]})
    if finished:
        updates.append({"range": f"{_col_letter(cols[HEADERS['finished_at']])}{row_number}", "values": [[finished]]})
    ws.batch_update(updates)


def _col_letter(col_1indexed: int) -> str:
    result = ""
    while col_1indexed:
        col_1indexed, rem = divmod(col_1indexed - 1, 26)
        result = chr(65 + rem) + result
    return result


def run_generation(project_dir: Path, blog: str, count: int) -> subprocess.CompletedProcess[str]:
    script = project_dir / "run_daily.sh"
    if not script.exists():
        raise FileNotFoundError(f"run_daily.sh が見つかりません: {script}")
    return subprocess.run(
        [str(script), blog, str(count)],
        cwd=str(project_dir),
        text=True,
        capture_output=True,
        timeout=60 * 60 * 3,
    )


def active_generation_lock(project_dir: Path) -> tuple[bool, str]:
    output_dir = project_dir / "output"
    if not output_dir.exists():
        return False, ""

    now = dt.datetime.now().timestamp()
    for lock_path in sorted(output_dir.glob(".*.lock")):
        try:
            age = now - lock_path.stat().st_mtime
            pid_text = lock_path.read_text(errors="replace").strip()
        except OSError:
            return True, f"{lock_path.name} を確認中"

        if age > LOCK_STALE_SECONDS:
            continue

        if not pid_text:
            return True, f"{lock_path.name} が存在"

        try:
            pid = int(pid_text)
        except ValueError:
            return True, f"{lock_path.name} が存在"

        try:
            os.kill(pid, 0)
            return True, f"{lock_path.name} / PID {pid}"
        except PermissionError:
            return True, f"{lock_path.name} / PID {pid}"
        except ProcessLookupError:
            continue

    return False, ""


def latest_blog_log(project_dir: Path, blog: str) -> Path:
    today = dt.datetime.now().strftime("%Y%m%d")
    return project_dir / "output" / f"{blog}_{today}.txt"


def generation_summary(project_dir: Path, blog: str) -> tuple[str, str]:
    log_path = latest_blog_log(project_dir, blog)
    if not log_path.exists():
        return "unknown", f"ログが見つかりません: {log_path}"

    text = log_path.read_text(errors="replace")[-12000:]
    if "生成件数  : 0件成功 / 0件失敗 / 計0件" in text or "成功=0件 / 重複スキップ=0件 / 失敗=0件 / 合計=0件" in text:
        return "none", "生成対象なし（候補がカニバリ除外または条件不一致）"
    if "✅ [" in text or "WP投稿完了" in text:
        return "generated", "正常終了"
    return "unknown", "正常終了（生成有無はログ確認）"


def process_once(args: argparse.Namespace) -> int:
    ws = load_sheet(args.spreadsheet_id, args.sheet_name, args.credentials)
    values = ws.get_all_values()
    cols = header_map(values)

    active, reason = active_generation_lock(args.project_dir)
    if active:
        print(f"[manual-worker] 記事生成中のため今回は待機します: {reason}")
        return 0

    processed = 0
    for row_number, row in enumerate(values[1:], start=2):
        status = cell(row, cols[HEADERS["status"]])
        if status != "未実行":
            continue

        active, reason = active_generation_lock(args.project_dir)
        if active:
            print(f"[manual-worker] 記事生成中のため行{row_number}は未実行のまま待機します: {reason}")
            return processed

        blog = cell(row, cols[HEADERS["blog"]]) or "workup-ai"
        count_raw = cell(row, cols[HEADERS["count"]]) or "1"
        try:
            count = max(1, int(float(count_raw)))
        except ValueError:
            count = 1

        started = now_jst()
        print(f"[manual-worker] start row={row_number} blog={blog} count={count}")
        update_status(ws, cols, row_number, "実行中", started=started)

        try:
            result = run_generation(args.project_dir, blog, count)
            finished = now_jst()
            if result.returncode == 0:
                summary_status, summary_memo = generation_summary(args.project_dir, blog)
                if summary_status == "none":
                    update_status(ws, cols, row_number, "対象なし", memo=summary_memo, finished=finished)
                    print(f"[manual-worker] no target row={row_number}")
                else:
                    update_status(ws, cols, row_number, "完了", memo=summary_memo, finished=finished)
                    print(f"[manual-worker] done row={row_number}")
            else:
                memo = (result.stderr or result.stdout or "")[-1500:]
                update_status(ws, cols, row_number, "失敗", memo=f"exit={result.returncode}\n{memo}", finished=finished)
                print(f"[manual-worker] failed row={row_number} exit={result.returncode}", file=sys.stderr)
        except Exception as exc:
            finished = now_jst()
            update_status(ws, cols, row_number, "失敗", memo=str(exc), finished=finished)
            print(f"[manual-worker] error row={row_number}: {exc}", file=sys.stderr)

        processed += 1
        if processed >= args.limit:
            break

    if processed == 0:
        print("[manual-worker] 未実行の依頼はありません。")
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="手動生成キューを拾って記事生成を実行します")
    parser.add_argument("--spreadsheet-id", default=os.getenv("MANUAL_QUEUE_SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID))
    parser.add_argument("--sheet-name", default=os.getenv("MANUAL_QUEUE_SHEET", DEFAULT_QUEUE_SHEET))
    parser.add_argument("--credentials", type=Path, default=Path(os.getenv("GOOGLE_CREDENTIALS_PATH", str(DEFAULT_CREDENTIALS))))
    parser.add_argument("--project-dir", type=Path, default=Path(os.getenv("ARTICLE_GENERATOR_DIR", str(DEFAULT_PROJECT_DIR))))
    parser.add_argument("--limit", type=int, default=1, help="1回の実行で処理する依頼数")
    args = parser.parse_args()
    process_once(args)


if __name__ == "__main__":
    main()
