"""
API安全装置 - 使用量上限・異常検知・緊急停止

チェック内容:
  1. STOP ファイル存在 → 即停止
  2. 1時間あたり $0.50 超 → 停止
  3. 1日あたり $2.00 超 → 停止

使用量は output/api_usage.json に累積記録（UTC日付・時刻ごと）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# 設定
# ============================================================
DAILY_LIMIT_USD   = 2.00   # 1日の上限（ドル）
HOURLY_LIMIT_USD  = 0.50   # 1時間の上限（ドル）

# Anthropic 価格（per 1M tokens）
PRICE = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output":  4.00},
}
DEFAULT_PRICE = {"input": 3.00, "output": 15.00}

# ファイルパス
_BASE_DIR  = Path(__file__).parent.parent
STOP_FILE  = _BASE_DIR / "STOP"
USAGE_FILE = _BASE_DIR / "output" / "api_usage.json"


# ============================================================
# 内部ユーティリティ
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
# 公開API
# ============================================================
def check_stop() -> None:
    """
    処理開始前に呼ぶ。停止条件に該当する場合は RuntimeError を送出する。

    停止条件:
      - STOP ファイルが存在する
      - 直近1時間の累積コスト >= HOURLY_LIMIT_USD
      - 当日（UTC）の累積コスト >= DAILY_LIMIT_USD
    """
    # 1. 緊急停止ファイル
    if STOP_FILE.exists():
        raise RuntimeError(
            f"[api_guard] 🛑 緊急停止: STOP ファイルが存在します ({STOP_FILE})\n"
            "  解除するには: rm ~/article-generator/STOP"
        )

    usage = _load_usage()
    now   = _now_utc()
    today = now.strftime("%Y-%m-%d")   # UTC日付
    hour  = now.strftime("%Y-%m-%dT%H")  # UTC時刻(時まで)

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

    # 3. 日次上限チェック
    daily_cost = sum(
        e["cost_usd"]
        for e in usage.get("entries", [])
        if e.get("date") == today
    )
    if daily_cost >= DAILY_LIMIT_USD:
        msg = (
            f"[api_guard] 🛑 日次上限超過: 本日のコスト "
            f"${daily_cost:.4f} >= ${DAILY_LIMIT_USD:.2f}\n"
            f"  翌日（UTC）まで待つか、DAILY_LIMIT_USD を引き上げてください。"
        )
        _log_event("daily_limit", msg, usage)
        raise RuntimeError(msg)

    print(
        f"[api_guard] ✅ 本日: ${daily_cost:.4f} / 1時間: ${hourly_cost:.4f}  "
        f"(上限 日次${DAILY_LIMIT_USD:.2f} / 時間${HOURLY_LIMIT_USD:.2f})"
    )


def record_usage(model: str, input_tokens: int, output_tokens: int, label: str = "") -> float:
    """
    APIコールの使用量を記録する。コスト（ドル）を返す。

    Args:
        model:         モデル名（例: "claude-sonnet-4-6"）
        input_tokens:  入力トークン数
        output_tokens: 出力トークン数
        label:         ログ用ラベル（記事タイトル等）

    Returns:
        今回のコスト（ドル）
    """
    cost  = _calc_cost(model, input_tokens, output_tokens)
    now   = _now_utc()
    entry = {
        "timestamp": now.isoformat(),
        "date":      now.strftime("%Y-%m-%d"),
        "hour":      now.strftime("%Y-%m-%dT%H"),
        "model":     model,
        "input_tokens":  input_tokens,
        "output_tokens": output_tokens,
        "cost_usd":  round(cost, 6),
        "label":     label,
    }

    usage = _load_usage()
    usage.setdefault("entries", []).append(entry)
    _save_usage(usage)

    print(
        f"[api_guard] 記録: {model} in={input_tokens} out={output_tokens} "
        f"→ ${cost:.4f}  ({label})"
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
    return {
        "date":          today,
        "calls":         len(entries),
        "input_tokens":  total_in,
        "output_tokens": total_out,
        "cost_usd":      round(total_cost, 6),
        "cost_jpy":      round(total_cost * 150, 2),
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
