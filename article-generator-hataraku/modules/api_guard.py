"""
API安全装置 - 使用量上限・異常検知・緊急停止

チェック内容:
  1. STOP ファイル存在 → 即停止
  2. 1時間あたり $1.00 超 → 停止
  3. デプロイ単体: 当日コスト >= DAILY_LIMIT_USD → 停止
  4. 全デプロイ合計: 当日コスト >= GLOBAL_DAILY_LIMIT_USD (≈¥300) → 停止
  5. 全デプロイ合計: 当日記事数 >= GLOBAL_DAILY_ARTICLE_LIMIT → 停止

使用量は output/api_usage.json に累積記録（UTC日付・時刻ごと）。
全体集計は ~/.article-generator-daily.json に共有記録。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# 設定
# ============================================================
DAILY_LIMIT_USD   = 2.00   # デプロイ単体の日次上限（ドル）
HOURLY_LIMIT_USD  = 1.00   # 1時間の上限（ドル）

# 全デプロイ合計の上限
GLOBAL_DAILY_LIMIT_USD     = 2.00   # ≈¥300（JPY/USD=150換算）
GLOBAL_DAILY_ARTICLE_LIMIT = 20     # 1日の合計生成記事数

JPY_PER_USD = 150  # 円換算レート

# Anthropic 価格（per 1M tokens）
PRICE = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output":  4.00},
}
DEFAULT_PRICE = {"input": 3.00, "output": 15.00}

# ファイルパス
_BASE_DIR   = Path(__file__).parent.parent
STOP_FILE   = _BASE_DIR / "STOP"
USAGE_FILE  = _BASE_DIR / "output" / "api_usage.json"
GLOBAL_FILE = Path.home() / ".article-generator-daily.json"  # 全デプロイ共有


# ============================================================
# 内部ユーティリティ（デプロイ単体）
# ============================================================
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load_usage() -> dict:
    if USAGE_FILE.exists():
        try:
            return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_usage(data: dict) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICE.get(model, DEFAULT_PRICE)
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


# ============================================================
# 全デプロイ共有ユーティリティ
# ============================================================
def _load_global() -> dict:
    if GLOBAL_FILE.exists():
        try:
            return json.loads(GLOBAL_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_global(data: dict) -> None:
    GLOBAL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _global_today_stats() -> tuple[float, int]:
    """(today_cost_usd, today_article_count) を返す。"""
    data  = _load_global()
    today = _now_utc().strftime("%Y-%m-%d")
    entries = data.get(today, {}).get("entries", [])
    cost     = sum(e.get("cost_usd", 0) for e in entries)
    articles = sum(1 for e in entries if e.get("is_article", False))
    return cost, articles


def _record_global(cost_usd: float, is_article: bool, label: str) -> None:
    """全デプロイ共有ファイルにコスト・記事数を追記する。"""
    data  = _load_global()
    today = _now_utc().strftime("%Y-%m-%d")
    deployment = _BASE_DIR.name
    day_data = data.setdefault(today, {"entries": []})
    day_data["entries"].append({
        "timestamp":  _now_utc().isoformat(),
        "deployment": deployment,
        "cost_usd":   round(cost_usd, 6),
        "is_article": is_article,
        "label":      label,
    })
    # 日次サマリーも更新
    all_entries = day_data["entries"]
    day_data["total_cost_usd"]   = round(sum(e["cost_usd"] for e in all_entries), 6)
    day_data["total_cost_jpy"]   = round(day_data["total_cost_usd"] * JPY_PER_USD, 1)
    day_data["total_articles"]   = sum(1 for e in all_entries if e.get("is_article"))
    _save_global(data)


# ============================================================
# 公開API
# ============================================================
def check_stop() -> None:
    """
    処理開始前に呼ぶ。停止条件に該当する場合は RuntimeError を送出する。

    停止条件:
      1. STOP ファイルが存在する
      2. 直近1時間の累積コスト >= HOURLY_LIMIT_USD
      3. デプロイ単体の日次コスト >= DAILY_LIMIT_USD
      4. 全体合計の日次コスト >= GLOBAL_DAILY_LIMIT_USD
      5. 全体合計の日次記事数 >= GLOBAL_DAILY_ARTICLE_LIMIT
    """
    # 1. 緊急停止ファイル
    if STOP_FILE.exists():
        raise RuntimeError(
            f"[api_guard] 🛑 緊急停止: STOP ファイルが存在します ({STOP_FILE})\n"
            "  解除するには: rm ~/article-generator/STOP"
        )

    usage = _load_usage()
    now   = _now_utc()
    today = now.strftime("%Y-%m-%d")
    hour  = now.strftime("%Y-%m-%dT%H")

    # 2. 1時間上限チェック
    hourly_cost = sum(
        e["cost_usd"]
        for e in usage.get("entries", [])
        if e.get("hour") == hour
    )
    if hourly_cost >= HOURLY_LIMIT_USD:
        msg = (
            f"[api_guard] 🛑 時間上限超過: 直近1時間のコスト "
            f"${hourly_cost:.4f} >= ${HOURLY_LIMIT_USD:.2f}\n"
            f"  1時間後に再試行するか、HOURLY_LIMIT_USD を引き上げてください。"
        )
        _log_event("hourly_limit", msg, usage)
        raise RuntimeError(msg)

    # 3. デプロイ単体の日次上限
    daily_cost = sum(
        e["cost_usd"]
        for e in usage.get("entries", [])
        if e.get("date") == today
    )
    if daily_cost >= DAILY_LIMIT_USD:
        msg = (
            f"[api_guard] 🛑 デプロイ日次上限超過: 本日のコスト "
            f"${daily_cost:.4f} >= ${DAILY_LIMIT_USD:.2f}\n"
            f"  翌日（UTC）まで待つか、DAILY_LIMIT_USD を引き上げてください。"
        )
        _log_event("daily_limit", msg, usage)
        raise RuntimeError(msg)

    # 4 & 5. 全デプロイ合計チェック
    global_cost, global_articles = _global_today_stats()

    if global_cost >= GLOBAL_DAILY_LIMIT_USD:
        msg = (
            f"[api_guard] 🛑 全体日次コスト上限: 本日合計 "
            f"${global_cost:.4f} (¥{global_cost*JPY_PER_USD:.0f}) "
            f">= ${GLOBAL_DAILY_LIMIT_USD:.2f} (¥{GLOBAL_DAILY_LIMIT_USD*JPY_PER_USD:.0f})\n"
            f"  翌日（UTC）にリセットされます。"
        )
        _log_event("global_daily_limit", msg, usage)
        raise RuntimeError(msg)

    if global_articles >= GLOBAL_DAILY_ARTICLE_LIMIT:
        msg = (
            f"[api_guard] 🛑 全体日次記事数上限: 本日合計 "
            f"{global_articles}件 >= {GLOBAL_DAILY_ARTICLE_LIMIT}件\n"
            f"  翌日（UTC）にリセットされます。"
        )
        _log_event("global_article_limit", msg, usage)
        raise RuntimeError(msg)

    print(
        f"[api_guard] ✅ 本日: ${daily_cost:.4f} / 1時間: ${hourly_cost:.4f}  "
        f"(上限 日次${DAILY_LIMIT_USD:.2f} / 時間${HOURLY_LIMIT_USD:.2f})  "
        f"全体: ${global_cost:.4f}(¥{global_cost*JPY_PER_USD:.0f}) / {global_articles}記事"
    )


def record_usage(model: str, input_tokens: int, output_tokens: int, label: str = "") -> float:
    """
    APIコールの使用量を記録する。コスト（ドル）を返す。
    label が "article:" で始まる場合は記事生成としてカウントする。
    """
    cost  = _calc_cost(model, input_tokens, output_tokens)
    now   = _now_utc()
    is_article = label.startswith("article:")

    # デプロイ単体ファイルに記録
    entry = {
        "timestamp":     now.isoformat(),
        "date":          now.strftime("%Y-%m-%d"),
        "hour":          now.strftime("%Y-%m-%dT%H"),
        "model":         model,
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "cost_usd":      round(cost, 6),
        "label":         label,
    }
    usage = _load_usage()
    usage.setdefault("entries", []).append(entry)
    _save_usage(usage)

    # 全体共有ファイルに記録
    _record_global(cost, is_article, label)

    today_cost = sum(
        e["cost_usd"] for e in usage.get("entries", [])
        if e.get("date") == now.strftime("%Y-%m-%d")
    )
    print(
        f"[api_guard] 記録: {model} in={input_tokens} out={output_tokens} "
        f"→ ${cost:.4f}  ({label})"
    )
    print(
        f"[api_guard] 本日の使用量: ${today_cost:.4f} / "
        f"¥{int(today_cost * JPY_PER_USD)} ({len(usage.get('entries', []))}回呼び出し)"
    )
    return cost


def daily_summary() -> dict:
    """本日（UTC）の使用サマリーを返す。"""
    usage = _load_usage()
    today = _now_utc().strftime("%Y-%m-%d")
    entries = [e for e in usage.get("entries", []) if e.get("date") == today]
    total_cost = sum(e["cost_usd"] for e in entries)
    total_in   = sum(e["input_tokens"] for e in entries)
    total_out  = sum(e["output_tokens"] for e in entries)
    global_cost, global_articles = _global_today_stats()
    return {
        "date":              today,
        "calls":             len(entries),
        "input_tokens":      total_in,
        "output_tokens":     total_out,
        "cost_usd":          round(total_cost, 6),
        "cost_jpy":          round(total_cost * JPY_PER_USD, 2),
        "global_cost_usd":   round(global_cost, 6),
        "global_cost_jpy":   round(global_cost * JPY_PER_USD, 2),
        "global_articles":   global_articles,
    }


# ============================================================
# 内部: イベントログ
# ============================================================
def _log_event(event_type: str, message: str, usage: dict) -> None:
    now = _now_utc()
    usage.setdefault("events", []).append({
        "timestamp": now.isoformat(),
        "type":      event_type,
        "message":   message,
    })
    _save_usage(usage)
    print(message)
