"""
DOKUSOU｜Import → KW シート移行チェッカー

DOKUSOU｜Import の aim判定済み・未インポート行を毎晩チェックし、
core_overlap / revenue_guard 等の条件を満たす KW を KW シートへ移行する。

Usage:
  python3 dokusou_importer.py                    # 全ブログ dry-run
  python3 dokusou_importer.py --blog workup-ai   # 1ブログ dry-run
  python3 dokusou_importer.py --blog workup-ai --apply  # 本番移行（将来）

Mode:
  dry-run (default): KWシートへの書き込みなし。LOG|DokusouImport に記録。
  apply  (--apply) : KWシートへ追記 + imported_to_kw=TRUE を更新。
"""
from __future__ import annotations

import json
import sys
import logging
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

# ─────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────
_IMPORT_SHEET   = "DOKUSOU｜Import"
_LOG_SHEET      = "LOG｜DokusouImport"
_SCOPES         = ["https://www.googleapis.com/auth/spreadsheets"]

# core_overlap.score のしきい値
_SCORE_HUMAN_REVIEW = 0.5   # これ以上は human_review
_SCORE_LOW          = 0.0   # これ未満なら確実に safe（現在は 0.0 or 0.333 or 0.5）

# duplicate_check でブロックする値
_DUPLICATE_BLOCK_VALUES = {"kw_already_exists", "block", "kw_duplicate"}

# LOG シートのヘッダー
_LOG_HEADER = [
    "run_at", "blog", "kw_sheet", "mode",
    "keyword", "action", "core_score", "core_matched_kw", "parent_kw", "note",
]

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 内部ユーティリティ
# ─────────────────────────────────────────────

def _parse_core_overlap(raw: str) -> dict:
    """core_overlap 列の JSON 文字列をパース。失敗時は {"risk": "unknown"} を返す。"""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"risk": "parse_error", "score": 0.0}


def _determine_action(
    kw: str,
    parent_kw: str,
    core: dict,
    existing_kws: set[str],
) -> tuple[str, str]:
    """
    KW の移行 action を決定する。

    Returns: (action, note)
      action: import_to_kw / parent_strengthen / internal_link_only /
              human_review / skip_kw_exists
    """
    kw_lower = kw.lower().strip()
    score       = core.get("score", 0.0)
    matched_url = core.get("matched_url", "")
    matched_kw  = core.get("matched_keyword", "")

    # KW シートに既存
    if kw_lower in existing_kws:
        return "skip_kw_exists", "KWシートに既存"

    # parent_kw 設定済み → 親 KW の sub-KW として強化
    if parent_kw:
        return "parent_strengthen", f"親KW={parent_kw}"

    # 既存記事 URL あり（risk=low でも matched_url がある場合）
    if matched_url:
        return "internal_link_only", f"既存記事={matched_url}"

    # スコアが高い → 要人確認
    if score >= _SCORE_HUMAN_REVIEW:
        note = f"score={score}"
        if matched_kw:
            note += f" / 類似KW={matched_kw!r}"
        return "human_review", note

    # クリア
    note = "" if score == 0.0 else f"score={score}"
    return "import_to_kw", note


# ─────────────────────────────────────────────
# シート I/O
# ─────────────────────────────────────────────

def _open_gc(credentials_path: str):
    creds = Credentials.from_service_account_file(credentials_path, scopes=_SCOPES)
    return gspread.authorize(creds)


def _ensure_log_sheet(ss, dry_run: bool) -> gspread.Worksheet | None:
    """LOG|DokusouImport シートを開く（なければ作成）。dry_run=True でも作成は行う。"""
    try:
        return ss.worksheet(_LOG_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=_LOG_SHEET, rows=5000, cols=len(_LOG_HEADER))
        ws.append_row(_LOG_HEADER, value_input_option="USER_ENTERED")
        log.info(f"[dokusou_importer] LOG シートを作成しました: {_LOG_SHEET}")
        return ws


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────

def check_blog(
    blog_name: str,
    kw_sheet_name: str,
    ss_id: str,
    credentials_path: str,
    dry_run: bool = True,
    apply_mode: bool = False,
) -> dict:
    """
    1ブログ分の DOKUSOU→KW 移行チェックを実行する。

    Returns:
        {
          "blog": str,
          "kw_sheet": str,
          "mode": str,
          "candidates": [{"row": int, "kw": str, "action": str, "note": str, ...}],
          "summary": {"import_to_kw": N, "parent_strengthen": N,
                      "internal_link_only": N, "human_review": N,
                      "skip_high": N, "skip_rev": N, "skip_imported": N,
                      "skip_kw_exists": N},
        }
    """
    gc = _open_gc(credentials_path)
    ss = gc.open_by_key(ss_id)

    # DOKUSOU｜Import 読み込み
    imp_ws  = ss.worksheet(_IMPORT_SHEET)
    imp_rows = imp_ws.get_all_values()
    if not imp_rows:
        log.warning(f"[dokusou_importer] {_IMPORT_SHEET} が空です")
        return {}

    imp_header = imp_rows[0]
    imp_col    = {h: i for i, h in enumerate(imp_header)}

    def g(row, k):
        return row[imp_col[k]].strip() if k in imp_col and len(row) > imp_col[k] else ""

    # KW シートの既存 keyword セットを取得
    kw_ws   = ss.worksheet(kw_sheet_name)
    kw_rows = kw_ws.get_all_values()
    kw_col  = {h: i for i, h in enumerate(kw_rows[0])} if kw_rows else {}
    existing_kws: set[str] = set()
    if kw_rows and "keyword" in kw_col:
        existing_kws = {
            r[kw_col["keyword"]].strip().lower()
            for r in kw_rows[1:]
            if r[kw_col["keyword"]].strip()
        }

    log.info(f"[dokusou_importer] {_IMPORT_SHEET}: {len(imp_rows)-1}行 / {kw_sheet_name}: {len(existing_kws)}件")

    candidates: list[dict] = []
    summary = {
        "import_to_kw": 0, "parent_strengthen": 0,
        "internal_link_only": 0, "human_review": 0,
        "skip_high": 0, "skip_rev": 0,
        "skip_imported": 0, "skip_kw_exists": 0,
    }

    for sheet_row, row in enumerate(imp_rows[1:], start=2):
        kw     = g(row, "キーワード")
        aim    = g(row, "aim")
        imp    = g(row, "imported_to_kw").upper()
        rev    = g(row, "revenue_guard").lower()
        tgt    = g(row, "target_kw_sheet")
        pkw    = g(row, "parent_kw")
        dup    = g(row, "duplicate_check").lower()
        core_raw = g(row, "core_overlap")

        # フィルタ: ターゲット KW シートが一致しない行は無視
        if tgt != kw_sheet_name:
            continue

        # フィルタ: aim 判定なし
        if not aim:
            continue

        # フィルタ: 既インポート
        if imp == "TRUE":
            summary["skip_imported"] += 1
            continue

        # フィルタ: revenue_guard NG
        if rev == "hit":
            summary["skip_rev"] += 1
            candidates.append({
                "row": sheet_row, "kw": kw, "action": "skip_rev",
                "core_score": 0, "core_matched_kw": "",
                "parent_kw": pkw, "note": "revenue_guard=hit",
            })
            continue

        # フィルタ: duplicate_check ブロック値
        if dup in _DUPLICATE_BLOCK_VALUES:
            candidates.append({
                "row": sheet_row, "kw": kw, "action": "skip_dup",
                "core_score": 0, "core_matched_kw": "",
                "parent_kw": pkw, "note": f"duplicate_check={dup}",
            })
            continue

        # core_overlap パース
        core  = _parse_core_overlap(core_raw)
        risk  = core.get("risk", "low")
        score = core.get("score", 0.0)

        # フィルタ: core_overlap 強
        if risk == "high":
            summary["skip_high"] += 1
            candidates.append({
                "row": sheet_row, "kw": kw, "action": "skip_high",
                "core_score": score,
                "core_matched_kw": core.get("matched_keyword", ""),
                "parent_kw": pkw,
                "note": f"core_overlap=high score={score} matched={core.get('matched_keyword','')}",
            })
            continue

        # action 決定
        action, note = _determine_action(kw, pkw, core, existing_kws)

        entry = {
            "row":            sheet_row,
            "kw":             kw,
            "action":         action,
            "core_score":     score,
            "core_matched_kw": core.get("matched_keyword", ""),
            "parent_kw":      pkw,
            "note":           note,
        }
        candidates.append(entry)

        if action in summary:
            summary[action] += 1

    # ── apply モード: KW シートへ追記 ─────────────────────
    if apply_mode and not dry_run:
        _apply_imports(
            kw_ws=kw_ws,
            imp_ws=imp_ws,
            imp_col=imp_col,
            candidates=candidates,
            kw_sheet_name=kw_sheet_name,
        )

    return {
        "blog":       blog_name,
        "kw_sheet":   kw_sheet_name,
        "mode":       "dry_run" if dry_run else "apply",
        "candidates": candidates,
        "summary":    summary,
    }


def _apply_imports(
    kw_ws, imp_ws, imp_col: dict,
    candidates: list[dict],
    kw_sheet_name: str,
) -> None:
    """
    import_to_kw / parent_strengthen の候補を KW シートへ追記し、
    DOKUSOU|Import の imported_to_kw 列を TRUE に更新する。
    """
    from datetime import date
    today = date.today().isoformat()

    imp_col_idx = imp_col.get("imported_to_kw", -1)
    imported_at_idx = imp_col.get("imported_at", -1)

    for c in candidates:
        if c["action"] not in ("import_to_kw", "parent_strengthen"):
            continue

        # KW シートへ追記
        kw_ws.append_row(
            [c["kw"], c.get("parent_kw", ""), "生成待ち", "", "独創", "", "", "", "", "", "", "", c.get("note", ""), "", "", "", ""],
            value_input_option="USER_ENTERED",
        )
        log.info(f"[dokusou_importer] KW追記: {c['kw']!r} → {kw_sheet_name}")

        # imported_to_kw = TRUE
        if imp_col_idx >= 0:
            imp_ws.update_cell(c["row"], imp_col_idx + 1, "TRUE")
        if imported_at_idx >= 0:
            imp_ws.update_cell(c["row"], imported_at_idx + 1, today)


# ─────────────────────────────────────────────
# ログ書き込み
# ─────────────────────────────────────────────

def write_log(
    ss_id: str,
    credentials_path: str,
    result: dict,
) -> None:
    """
    check_blog() の結果を LOG｜DokusouImport シートに書き込む。
    dry_run モードでも記録する（実行履歴として）。
    """
    gc = _open_gc(credentials_path)
    ss = gc.open_by_key(ss_id)
    log_ws = _ensure_log_sheet(ss, dry_run=False)
    if log_ws is None:
        return

    run_at    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    blog      = result.get("blog", "")
    kw_sheet  = result.get("kw_sheet", "")
    mode      = result.get("mode", "dry_run")

    rows_to_append = []
    for c in result.get("candidates", []):
        rows_to_append.append([
            run_at,
            blog,
            kw_sheet,
            mode,
            c["kw"],
            c["action"],
            str(c.get("core_score", "")),
            c.get("core_matched_kw", ""),
            c.get("parent_kw", ""),
            c.get("note", ""),
        ])

    if rows_to_append:
        log_ws.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        log.info(f"[dokusou_importer] LOG書き込み: {len(rows_to_append)}件 → {_LOG_SHEET}")


# ─────────────────────────────────────────────
# レポート出力
# ─────────────────────────────────────────────

def print_report(result: dict) -> None:
    """dry-run レポートをコンソールに出力する。"""
    blog     = result.get("blog", "?")
    kw_sheet = result.get("kw_sheet", "?")
    mode     = result.get("mode", "dry_run")
    summary  = result.get("summary", {})
    candidates = result.get("candidates", [])

    print()
    print("=" * 60)
    print(f"DOKUSOU｜Import チェック結果 [{blog}] → {kw_sheet}")
    print(f"モード: {mode.upper()}  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    total_action = (summary.get("import_to_kw", 0)
                    + summary.get("parent_strengthen", 0)
                    + summary.get("internal_link_only", 0)
                    + summary.get("human_review", 0))
    print(f"\n【アクション対象】 {total_action}件")
    print(f"  import_to_kw       : {summary.get('import_to_kw', 0):3d}件  ← KWシートへ追加予定")
    print(f"  parent_strengthen  : {summary.get('parent_strengthen', 0):3d}件  ← 既存KWのsub-KWへ昇格")
    print(f"  internal_link_only : {summary.get('internal_link_only', 0):3d}件  ← 内部リンクのみ利用")
    print(f"  human_review       : {summary.get('human_review', 0):3d}件  ← 人的確認が必要")

    print(f"\n【スキップ】")
    print(f"  core_overlap=high  : {summary.get('skip_high', 0):3d}件  （カニバリ強）")
    print(f"  revenue_guard=hit  : {summary.get('skip_rev', 0):3d}件  （収益NG）")
    print(f"  imported=TRUE      : {summary.get('skip_imported', 0):3d}件  （インポート済み）")
    print(f"  KWシート既存       : {summary.get('skip_kw_exists', 0):3d}件  （既登録）")

    # import_to_kw 詳細
    import_cands = [c for c in candidates if c["action"] == "import_to_kw"]
    if import_cands:
        print(f"\n【import_to_kw 候補 {len(import_cands)}件】")
        for c in import_cands:
            note = f"  ({c['note']})" if c.get("note") else ""
            print(f"  行{c['row']:3d}: {c['kw']!r}{note}")

    # parent_strengthen 詳細
    ps_cands = [c for c in candidates if c["action"] == "parent_strengthen"]
    if ps_cands:
        print(f"\n【parent_strengthen 候補 {len(ps_cands)}件】")
        for c in ps_cands:
            print(f"  行{c['row']:3d}: {c['kw']!r}  → 親KW: {c['parent_kw']!r}")

    # human_review 詳細
    hr_cands = [c for c in candidates if c["action"] == "human_review"]
    if hr_cands:
        print(f"\n【human_review 候補 {len(hr_cands)}件】")
        for c in hr_cands[:10]:
            print(f"  行{c['row']:3d}: {c['kw']!r}  {c.get('note','')}")
        if len(hr_cands) > 10:
            print(f"  ... 他 {len(hr_cands)-10}件")

    # skip_high 詳細（先頭5件）
    high_cands = [c for c in candidates if c["action"] == "skip_high"]
    if high_cands:
        print(f"\n【skip: core_overlap=high {len(high_cands)}件 (先頭5件)】")
        for c in high_cands[:5]:
            print(f"  行{c['row']:3d}: {c['kw']!r}  → {c.get('note','')}")

    print()
    if mode == "dry_run":
        print("▶ dry-run: KWシートへの書き込みはしていません")
        print("▶ LOG｜DokusouImport に実行ログを記録しました")
        print("▶ apply モードへ切り替える場合: --apply フラグを追加してください")
    print("=" * 60)


# ─────────────────────────────────────────────
# CLI エントリポイント
# ─────────────────────────────────────────────

def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="DOKUSOU｜Import → KW シート移行チェッカー")
    parser.add_argument("--blog",  default=None, help="ブログ名 (例: workup-ai)")
    parser.add_argument("--apply", action="store_true",
                        help="本番移行モード（KWシートへ書き込む）。指定なし=dry-run")
    args = parser.parse_args()

    dry_run = not args.apply

    # ── プロジェクトの設定を読み込む
    sys.path.insert(0, ".")
    try:
        from config import GOOGLE_CREDENTIALS_PATH
        from generate_lite import load_blog_config, list_blogs
    except ImportError as e:
        print(f"設定読み込みエラー: {e}")
        sys.exit(1)

    # ── 対象ブログの決定
    if args.blog:
        target_blogs = [args.blog]
    else:
        # デフォルト: experience_ss_id が設定されているブログすべて
        target_blogs = []
        for bn in list_blogs():
            try:
                cfg = load_blog_config(bn)
                if cfg.extra.get("experience_ss_id"):
                    target_blogs.append(bn)
            except Exception:
                pass

    if not target_blogs:
        log.error("対象ブログが見つかりません")
        sys.exit(1)

    mode_label = "DRY RUN" if dry_run else "APPLY"
    log.info(f"[dokusou_importer] 開始 ({mode_label}) 対象ブログ: {target_blogs}")

    for blog_name in target_blogs:
        try:
            cfg = load_blog_config(blog_name)
            ss_id = cfg.extra.get("experience_ss_id", "")
            candidate_sheet = cfg.candidate_sheet  # KW｜AIVice 等

            if not ss_id:
                log.warning(f"[{blog_name}] experience_ss_id 未設定 → スキップ")
                continue

            if not candidate_sheet:
                log.warning(f"[{blog_name}] candidate_sheet 未設定 → スキップ")
                continue

            result = check_blog(
                blog_name=blog_name,
                kw_sheet_name=candidate_sheet,
                ss_id=ss_id,
                credentials_path=GOOGLE_CREDENTIALS_PATH,
                dry_run=dry_run,
                apply_mode=args.apply,
            )

            print_report(result)

            # LOG シートへ記録（dry-run / apply 両方）
            write_log(ss_id, GOOGLE_CREDENTIALS_PATH, result)

        except Exception as e:
            log.error(f"[{blog_name}] エラー: {e}", exc_info=True)

    log.info(f"[dokusou_importer] 完了")


if __name__ == "__main__":
    main()
