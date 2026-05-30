"""
DISCOVERY｜Seeds → AIM｜Discovery 補充ルーチン

DISCOVERY｜Seeds シートから enabled=TRUE の親KWを読み取り、
theme_type に応じたルールベース展開で関連KWを生成し、
4ソース重複除外 + 一次フィルター後に AIM｜Discovery へ追加する。

LLM は使用しない（ルールベース完全）。
KW｜AIVice への直接追加はしない（AIM|Discovery 経由のみ）。

Usage:
  python3 scripts/discovery_seed_runner.py --blog workup-ai --dry-run
  python3 scripts/discovery_seed_runner.py --blog workup-ai --apply
  python3 scripts/discovery_seed_runner.py --blog workup-ai --apply --force
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

# プロジェクトルートを path に追加
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import gspread
from google.oauth2.service_account import Credentials

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# シート名
# ─────────────────────────────────────────────
_SEEDS_SHEET     = "DISCOVERY｜Seeds"
_DISCOVERY_SHEET = "AIM｜Discovery"

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ─────────────────────────────────────────────
# DISCOVERY｜Seeds ヘッダー
# ─────────────────────────────────────────────
_SEEDS_HEADER = [
    "blog_id", "parent_kw", "theme_type", "enabled",
    "frequency", "max_fetch", "last_run", "next_run", "status", "memo",
]

# ─────────────────────────────────────────────
# theme_type → サフィックステンプレ
# ─────────────────────────────────────────────
_THEME_SUFFIXES: dict[str, list[str]] = {
    # プロンプト・テンプレ系
    "prompt": [
        "プロンプト集",
        "テンプレ",
        "コピペテンプレ",
        "実務テンプレ",
        "プロンプト 書き方",
        "プロンプト コツ",
        "プロンプト 例",
        "プロンプト 保存版",
        "プロンプト 初心者",
        "プロンプト まとめ",
    ],
    # ワークフロー・自動化系
    "workflow": [
        "ワークフロー",
        "自動化フロー",
        "自動化 やり方",
        "自動化 設定",
        "自動化 手順",
        "SEOワークフロー",
        "投稿自動化",
        "ブログ自動化",
        "自動化構成",
        "保存版",
    ],
    # 動画系
    "video": [
        "動画生成",
        "台本テンプレ",
        "リール構成テンプレ",
        "ショート動画プロンプト",
        "動画 テンプレ",
        "動画 自動化",
        "動画 投稿テンプレ",
        "SNS投稿テンプレ",
        "投稿カレンダー",
        "動画 構成",
    ],
    # SNS 投稿系
    "sns": [
        "X投稿テンプレ",
        "SNS投稿テンプレ",
        "投稿カレンダー",
        "投稿テンプレ",
        "SNS自動化",
        "投稿 自動化",
        "投稿 コツ",
        "投稿 最適化",
    ],
    # オートメーション・業務効率
    "automation": [
        "自動化 初心者",
        "自動化 ツール",
        "全自動化",
        "業務効率化",
        "時短 ワークフロー",
        "タスク自動化",
        "API 連携",
        "n8n 連携",
        "Zapier 連携",
    ],
    # クリエイター・発信者向け
    "creator": [
        "個人ブログ 勝ち方",
        "収益化 できない",
        "収益化 方法",
        "ブログ 使い方",
        "note 書き方",
        "初心者 始め方",
        "副業 始め方",
        "在宅ワーク",
    ],
    # Google サジェスト系（感情・悩み）
    "pain": [
        "疲れた",
        "使いこなせない",
        "何から始める",
        "やめた",
        "怖い",
        "迷う",
        "本音",
        "失敗",
        "話題 どうする",
        "使うべきか",
        "いらない",
        "続かない",
        "難しい",
        "代替",
        "課金 きつい",
    ],
    # SEO・流入系
    "seo": [
        "クリック 減った",
        "検索流入 減った",
        "引用される 方法",
        "順位 落ちた",
        "上位表示 できない",
        "SEO 対策",
        "対策 個人ブログ",
        "順位チェック",
        "内部リンク 設定",
    ],
    # 使い方・基本系
    "howto": [
        "使い方",
        "始め方",
        "設定 方法",
        "できること",
        "料金",
        "無料",
        "登録 方法",
        "ダウンロード",
        "スマホ",
        "PC",
    ],
    # 比較・選択系
    "compare": [
        "比較",
        "違い",
        "どっち",
        "おすすめ",
        "メリット デメリット",
        "評判",
        "口コミ",
        "選び方",
    ],
}

# ─────────────────────────────────────────────
# theme_type → AIM|Discovery スコア初期値
# ─────────────────────────────────────────────
_THEME_SCORES: dict[str, dict[str, str]] = {
    "prompt":     {"prompt_value_score": "高", "copy_paste_value": "高",
                   "workflow_fit": "中", "automation_fit": "低", "creator_fit": "中",
                   "codoc_fit": "高", "note_fit": "高", "aio_resistant_asset": "高"},
    "workflow":   {"prompt_value_score": "中", "copy_paste_value": "中",
                   "workflow_fit": "高", "automation_fit": "高", "creator_fit": "低",
                   "codoc_fit": "中", "note_fit": "低", "aio_resistant_asset": "中"},
    "video":      {"prompt_value_score": "高", "copy_paste_value": "高",
                   "workflow_fit": "中", "automation_fit": "低", "creator_fit": "高",
                   "codoc_fit": "高", "note_fit": "中", "aio_resistant_asset": "高"},
    "sns":        {"prompt_value_score": "中", "copy_paste_value": "高",
                   "workflow_fit": "低", "automation_fit": "低", "creator_fit": "高",
                   "codoc_fit": "中", "note_fit": "中", "aio_resistant_asset": "中"},
    "automation": {"prompt_value_score": "低", "copy_paste_value": "低",
                   "workflow_fit": "高", "automation_fit": "高", "creator_fit": "低",
                   "codoc_fit": "中", "note_fit": "低", "aio_resistant_asset": "低"},
    "creator":    {"prompt_value_score": "中", "copy_paste_value": "中",
                   "workflow_fit": "低", "automation_fit": "低", "creator_fit": "高",
                   "codoc_fit": "高", "note_fit": "高", "aio_resistant_asset": "高"},
    "pain":       {"prompt_value_score": "中", "copy_paste_value": "低",
                   "workflow_fit": "低", "automation_fit": "低", "creator_fit": "中",
                   "codoc_fit": "中", "note_fit": "中", "aio_resistant_asset": "高"},
    "seo":        {"prompt_value_score": "低", "copy_paste_value": "低",
                   "workflow_fit": "中", "automation_fit": "低", "creator_fit": "中",
                   "codoc_fit": "低", "note_fit": "低", "aio_resistant_asset": "高"},
    "howto":      {"prompt_value_score": "低", "copy_paste_value": "低",
                   "workflow_fit": "低", "automation_fit": "低", "creator_fit": "中",
                   "codoc_fit": "中", "note_fit": "中", "aio_resistant_asset": "低"},
    "compare":    {"prompt_value_score": "低", "copy_paste_value": "低",
                   "workflow_fit": "低", "automation_fit": "低", "creator_fit": "中",
                   "codoc_fit": "中", "note_fit": "中", "aio_resistant_asset": "低"},
}

_DEFAULT_SCORES = {
    "prompt_value_score": "中", "copy_paste_value": "低",
    "workflow_fit": "低", "automation_fit": "低", "creator_fit": "低",
    "codoc_fit": "低", "note_fit": "低", "aio_resistant_asset": "低",
}

# ─────────────────────────────────────────────
# KW 展開
# ─────────────────────────────────────────────

def _expand_kws(parent_kw: str, theme_types: list[str], max_fetch: int) -> list[dict]:
    """
    parent_kw と theme_type リストからルールベースで関連KWを生成する。

    Returns: [{"kw": str, "source_type": str, "theme_type": str}]
    """
    candidates: list[dict] = []
    seen_kw: set[str] = set()

    for theme in theme_types:
        theme = theme.strip()
        suffixes = _THEME_SUFFIXES.get(theme, [])
        src_type = _theme_to_source_type(theme)
        for suffix in suffixes:
            kw = f"{parent_kw} {suffix}"
            kw_lower = kw.lower()
            if kw_lower not in seen_kw:
                seen_kw.add(kw_lower)
                candidates.append({
                    "kw":          kw,
                    "source_type": src_type,
                    "theme_type":  theme,
                })
            if len(candidates) >= max_fetch:
                return candidates

    return candidates[:max_fetch]


def _theme_to_source_type(theme: str) -> str:
    if theme in ("prompt", "workflow", "video", "sns", "automation", "creator"):
        return "seed_expansion"
    if theme in ("pain",):
        return "seed_expansion_suggest"
    if theme in ("seo",):
        return "seed_expansion_seo"
    return "seed_expansion"


# ─────────────────────────────────────────────
# 一次フィルタ（ルールベース）
# ─────────────────────────────────────────────

def _primary_filter(kw: str, ng_keywords: list[str]) -> tuple[bool, str]:
    """
    KW の一次フィルタを実施する。

    Returns: (pass: bool, reason: str)
    """
    # 文字数チェック
    if len(kw) < 4:
        return False, "too_short"
    if len(kw) > 50:
        return False, "too_long"

    # 純粋英数字のみ（日本語を含まない）は除外
    import re
    if not re.search(r'[　-鿿＀-￯]', kw):
        return False, "no_japanese"

    # 知恵袋・Q&Aノイズ
    noise_patterns = ["知恵袋", "yahoo", "Yahoo", "教えて", "回答", "ベストアンサー"]
    for pat in noise_patterns:
        if pat in kw:
            return False, f"noise:{pat}"

    # NG キーワード（ブログ設定）
    kw_lower = kw.lower()
    for ng in ng_keywords:
        if ng.lower() in kw_lower:
            return False, f"ng_keyword:{ng}"

    return True, ""


# ─────────────────────────────────────────────
# 重複チェック（4ソース）
# ─────────────────────────────────────────────

def _build_dedup_sets(ss, kw_sheet_name: str) -> dict[str, set[str]]:
    """
    AIM|Discovery / DOKUSOU|Import / KW|AIVice の既存 KW セットを返す。
    """
    result: dict[str, set[str]] = {
        "discovery": set(),
        "dokusou":   set(),
        "kw_sheet":  set(),
    }

    # AIM|Discovery
    try:
        ws = ss.worksheet(_DISCOVERY_SHEET)
        rows = ws.get_all_values()
        if rows:
            col_idx = rows[0].index("keyword") if "keyword" in rows[0] else 0
            result["discovery"] = {r[col_idx].strip().lower() for r in rows[1:] if r[col_idx].strip()}
    except Exception as e:
        log.warning(f"AIM|Discovery 読み込みエラー: {e}")

    # DOKUSOU|Import
    try:
        ws = ss.worksheet("DOKUSOU｜Import")
        rows = ws.get_all_values()
        if rows:
            col_idx = rows[0].index("キーワード") if "キーワード" in rows[0] else 0
            result["dokusou"] = {r[col_idx].strip().lower() for r in rows[1:] if r[col_idx].strip()}
    except Exception as e:
        log.warning(f"DOKUSOU|Import 読み込みエラー: {e}")

    # KW シート
    try:
        ws = ss.worksheet(kw_sheet_name)
        rows = ws.get_all_values()
        if rows and "keyword" in rows[0]:
            col_idx = rows[0].index("keyword")
            result["kw_sheet"] = {r[col_idx].strip().lower() for r in rows[1:] if r[col_idx].strip()}
    except Exception as e:
        log.warning(f"{kw_sheet_name} 読み込みエラー: {e}")

    log.info(f"[dedup] discovery={len(result['discovery'])} "
             f"dokusou={len(result['dokusou'])} kw_sheet={len(result['kw_sheet'])}")
    return result


def _is_duplicate(kw: str, dedup: dict[str, set[str]]) -> tuple[bool, str]:
    kw_lower = kw.lower().strip()
    for src, kw_set in dedup.items():
        if kw_lower in kw_set:
            return True, src
    return False, ""


# ─────────────────────────────────────────────
# AIM|Discovery 行生成
# ─────────────────────────────────────────────

_DISCOVERY_HEADER = [
    "keyword", "source_type", "source_query", "status", "filter_status", "filter_reason",
    "pre_dokusou_score", "ready_for_dokusou", "noise_flags", "language_flag", "typo_flag",
    "chiebukuro_flag", "volume", "volume_flag", "trend_flag", "exception_reason",
    "next_action", "prompt_value_score", "copy_paste_value", "workflow_fit",
    "automation_fit", "creator_fit", "codoc_fit", "note_fit", "aio_resistant_asset",
    "guard_action", "guard_reason", "parent_kw", "matched_keyword", "matched_url",
    "created_at", "memo", "search_volume", "volume_source", "volume_checked_at", "intent_score",
]


def _build_discovery_row(kw: str, parent_kw: str, source_type: str,
                          theme_type: str, seed_memo: str = "") -> list[str]:
    """AIM|Discovery に追記する1行を生成する。"""
    scores = {**_DEFAULT_SCORES, **_THEME_SCORES.get(theme_type, {})}
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+09:00")

    row_dict = {
        "keyword":            kw,
        "source_type":        source_type,
        "source_query":       parent_kw,
        "status":             "pre_dokusou",
        "filter_status":      "pre_dokusou",
        "filter_reason":      "",
        "pre_dokusou_score":  "",
        "ready_for_dokusou":  "FALSE",
        "noise_flags":        "",
        "language_flag":      "ja_or_mixed",
        "typo_flag":          "ok",
        "chiebukuro_flag":    "no",
        "volume":             "unknown",
        "volume_flag":        "unknown",
        "trend_flag":         "",
        "exception_reason":   "",
        "next_action":        "",
        "prompt_value_score": scores["prompt_value_score"],
        "copy_paste_value":   scores["copy_paste_value"],
        "workflow_fit":       scores["workflow_fit"],
        "automation_fit":     scores["automation_fit"],
        "creator_fit":        scores["creator_fit"],
        "codoc_fit":          scores["codoc_fit"],
        "note_fit":           scores["note_fit"],
        "aio_resistant_asset": scores["aio_resistant_asset"],
        "guard_action":       "",
        "guard_reason":       "",
        "parent_kw":          parent_kw,
        "matched_keyword":    "",
        "matched_url":        "",
        "created_at":         now_iso,
        "memo":               seed_memo or f"seed_expansion/{theme_type}",
        "search_volume":      "",
        "volume_source":      "",
        "volume_checked_at":  "",
        "intent_score":       "",
    }

    return [row_dict.get(h, "") for h in _DISCOVERY_HEADER]


# ─────────────────────────────────────────────
# Seeds シート I/O
# ─────────────────────────────────────────────

def _open_or_create_seeds(ss) -> gspread.Worksheet:
    try:
        return ss.worksheet(_SEEDS_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=_SEEDS_SHEET, rows=500, cols=len(_SEEDS_HEADER))
        ws.append_row(_SEEDS_HEADER, value_input_option="USER_ENTERED")
        log.info(f"[seeds] {_SEEDS_SHEET} を新規作成しました")
        return ws


def _load_seeds(ws, blog_id_filter: str) -> list[dict]:
    """enabled=TRUE の Seeds を返す。"""
    rows = ws.get_all_values()
    if not rows:
        return []
    header = rows[0]
    col = {h: i for i, h in enumerate(header)}

    def g(row, k): return row[col[k]].strip() if k in col and len(row) > col[k] else ""

    seeds = []
    for i, row in enumerate(rows[1:], start=2):
        if g(row, "blog_id") != blog_id_filter:
            continue
        if g(row, "enabled").upper() != "TRUE":
            continue
        seeds.append({
            "_sheet_row": i,
            "blog_id":    g(row, "blog_id"),
            "parent_kw":  g(row, "parent_kw"),
            "theme_type": g(row, "theme_type"),
            "enabled":    g(row, "enabled"),
            "frequency":  g(row, "frequency") or "weekly",
            "max_fetch":  int(g(row, "max_fetch") or "50"),
            "last_run":   g(row, "last_run"),
            "next_run":   g(row, "next_run"),
            "status":     g(row, "status"),
            "memo":       g(row, "memo"),
        })
    return seeds


def _is_due(seed: dict, force: bool) -> bool:
    """next_run が未来なら False（スキップ）。force=True なら常に True。"""
    if force:
        return True
    next_run_str = seed.get("next_run", "").strip()
    if not next_run_str:
        return True
    try:
        next_run = datetime.fromisoformat(next_run_str)
        return datetime.now() >= next_run
    except ValueError:
        return True


def _calc_next_run(frequency: str) -> str:
    now = datetime.now()
    if frequency == "daily":
        delta = timedelta(days=1)
    elif frequency == "biweekly":
        delta = timedelta(days=3)
    elif frequency == "monthly":
        delta = timedelta(days=30)
    else:  # weekly (default)
        delta = timedelta(days=7)
    return (now + delta).strftime("%Y-%m-%d")


def _update_seed_row(ws, seed: dict, added: int, skipped: int, apply_mode: bool) -> None:
    """last_run / next_run / status を更新する（apply モードのみ）。"""
    if not apply_mode:
        return
    row_num   = seed["_sheet_row"]
    now_str   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    next_run  = _calc_next_run(seed["frequency"])
    status    = f"ok: +{added}件 skip:{skipped}件"

    header = ws.row_values(1)
    col = {h: i + 1 for i, h in enumerate(header)}  # 1-indexed

    if "last_run"  in col: ws.update_cell(row_num, col["last_run"],  now_str)
    if "next_run"  in col: ws.update_cell(row_num, col["next_run"],  next_run)
    if "status"    in col: ws.update_cell(row_num, col["status"],    status)


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────

def run_for_blog(
    blog_name: str,
    kw_sheet_name: str,
    ng_keywords: list[str],
    ss_id: str,
    credentials_path: str,
    dry_run: bool = True,
    force: bool = False,
) -> dict:
    """
    1ブログ分の Discovery 補充を実行する。

    Returns: {
      "blog": str,
      "seeds_processed": int,
      "results": [{"seed": dict, "added": int, "skipped": int, "kws": [...]}],
    }
    """
    from config import GOOGLE_CREDENTIALS_PATH  # noqa

    creds = Credentials.from_service_account_file(credentials_path, scopes=_SCOPES)
    gc    = gspread.authorize(creds)
    ss    = gc.open_by_key(ss_id)

    seeds_ws = _open_or_create_seeds(ss)
    seeds    = _load_seeds(seeds_ws, blog_id_filter=blog_name)

    if not seeds:
        log.warning(f"[{blog_name}] enabled=TRUE の Seeds が見つかりません")
        return {"blog": blog_name, "seeds_processed": 0, "results": []}

    dedup = _build_dedup_sets(ss, kw_sheet_name)

    # apply 用: AIM|Discovery のワークシート
    disc_ws = ss.worksheet(_DISCOVERY_SHEET) if not dry_run else None

    all_results = []

    for seed in seeds:
        parent_kw  = seed["parent_kw"]
        theme_list = [t.strip() for t in seed["theme_type"].split(",") if t.strip()]
        max_fetch  = seed["max_fetch"]

        if not _is_due(seed, force):
            log.info(f"[{parent_kw}] next_run={seed['next_run']} → スキップ（--force で強制実行）")
            continue

        # KW 展開
        expanded = _expand_kws(parent_kw, theme_list, max_fetch * 3)  # 余裕を持って展開

        accepted: list[dict] = []
        skipped:  list[dict] = []

        for item in expanded:
            kw = item["kw"]

            # 重複チェック
            is_dup, dup_src = _is_duplicate(kw, dedup)
            if is_dup:
                skipped.append({**item, "skip_reason": f"dup:{dup_src}"})
                continue

            # 一次フィルタ
            ok, reason = _primary_filter(kw, ng_keywords)
            if not ok:
                skipped.append({**item, "skip_reason": f"filter:{reason}"})
                continue

            # max_fetch 上限
            if len(accepted) >= max_fetch:
                skipped.append({**item, "skip_reason": "max_fetch"})
                continue

            accepted.append(item)
            # dedup セットに追加（同一ランナー内の重複防止）
            dedup["discovery"].add(kw.lower())

        # apply モード: AIM|Discovery に追記
        if not dry_run and disc_ws and accepted:
            rows_to_add = [
                _build_discovery_row(
                    kw=item["kw"],
                    parent_kw=parent_kw,
                    source_type=item["source_type"],
                    theme_type=item["theme_type"],
                    seed_memo=seed.get("memo", ""),
                )
                for item in accepted
            ]
            disc_ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")
            log.info(f"[{parent_kw}] AIM|Discovery に {len(rows_to_add)}件 追記")
            _update_seed_row(seeds_ws, seed, len(accepted), len(skipped), apply_mode=True)
        elif dry_run:
            log.info(f"[{parent_kw}] DRY RUN: +{len(accepted)}件 / skip:{len(skipped)}件")

        all_results.append({
            "seed":    seed,
            "added":   len(accepted),
            "skipped": len(skipped),
            "kws":     accepted,
            "skipped_kws": skipped,
        })

    return {
        "blog":             blog_name,
        "seeds_processed":  len(all_results),
        "results":          all_results,
    }


# ─────────────────────────────────────────────
# レポート出力
# ─────────────────────────────────────────────

def print_report(result: dict, dry_run: bool) -> None:
    blog    = result.get("blog", "?")
    results = result.get("results", [])

    total_added   = sum(r["added"]   for r in results)
    total_skipped = sum(r["skipped"] for r in results)

    mode = "DRY RUN" if dry_run else "APPLY"
    print()
    print("=" * 60)
    print(f"Discovery Seeds 補充レポート [{blog}]  {mode}")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"\n処理シード数 : {result['seeds_processed']}件")
    print(f"追加候補合計 : {total_added}件")
    print(f"スキップ合計 : {total_skipped}件")
    print()

    for r in results:
        seed = r["seed"]
        print(f"── {seed['parent_kw']}  [theme: {seed['theme_type']}]  max={seed['max_fetch']}")
        print(f"   +{r['added']}件 追加 / {r['skipped']}件 スキップ")

        if r["kws"]:
            print(f"   【追加候補 {min(len(r['kws']), 10)}件】")
            for item in r["kws"][:10]:
                print(f"     {item['kw']!r}")
            if len(r["kws"]) > 10:
                print(f"     ... 他 {len(r['kws'])-10}件")

        # スキップ理由の集計
        from collections import Counter
        skip_reasons = Counter(item["skip_reason"] for item in r.get("skipped_kws", []))
        if skip_reasons:
            print(f"   【スキップ理由】")
            for reason, cnt in skip_reasons.most_common():
                print(f"     {reason}: {cnt}件")
        print()

    if dry_run:
        print("▶ dry-run: AIM|Discovery への書き込みはしていません")
        print("▶ apply モード: --apply フラグを追加して実行してください")
    else:
        print(f"▶ AIM|Discovery に合計 {total_added}件 追記しました")
        print("▶ DISCOVERY|Seeds の last_run / next_run / status を更新しました")
    print("=" * 60)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="DISCOVERY｜Seeds → AIM｜Discovery 補充ルーチン"
    )
    parser.add_argument("--blog",    default="workup-ai", help="ブログ名 (例: workup-ai)")
    parser.add_argument("--apply",   action="store_true",  help="本番適用（書き込みあり）")
    parser.add_argument("--dry-run", action="store_true",  dest="dry_run_flag",
                        help="dry-run（デフォルト動作と同等、明示用）")
    parser.add_argument("--force",   action="store_true",  help="next_run を無視して強制実行")
    args = parser.parse_args()

    dry_run = not args.apply

    try:
        from config import GOOGLE_CREDENTIALS_PATH
        from generate_lite import load_blog_config
    except ImportError as e:
        print(f"設定読み込みエラー: {e}")
        sys.exit(1)

    try:
        cfg = load_blog_config(args.blog)
    except Exception as e:
        print(f"ブログ設定読み込みエラー [{args.blog}]: {e}")
        sys.exit(1)

    ss_id           = cfg.extra.get("experience_ss_id", "")
    kw_sheet_name   = cfg.candidate_sheet or "KW｜AIVice"
    ng_keywords     = cfg.ng_keywords or []

    if not ss_id:
        print(f"[{args.blog}] experience_ss_id が未設定です")
        sys.exit(1)

    mode_label = "DRY RUN" if dry_run else "APPLY"
    log.info(f"[discovery_seed_runner] 開始 ({mode_label}) blog={args.blog} "
             f"kw_sheet={kw_sheet_name} force={args.force}")

    result = run_for_blog(
        blog_name=args.blog,
        kw_sheet_name=kw_sheet_name,
        ng_keywords=ng_keywords,
        ss_id=ss_id,
        credentials_path=GOOGLE_CREDENTIALS_PATH,
        dry_run=dry_run,
        force=args.force,
    )

    print_report(result, dry_run=dry_run)


if __name__ == "__main__":
    main()
