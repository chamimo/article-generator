#!/bin/bash
# AIVICE (workup-ai.com) 毎日自動記事生成
# cron: 0 4 * * *

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"
PYTHON="/opt/homebrew/bin/python3"

PROJECT_DIR="/Users/yama/article-generator-aivice"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/log_$(date +%Y%m%d).txt"

cd "$PROJECT_DIR" || exit 1

LOCK_FILE="$LOG_DIR/.aivice.lock"

# 既に実行中なら即終了
if [ -f "$LOCK_FILE" ]; then
    EXISTING_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "⚠️  [AIVICE] 既に実行中です (PID: $EXISTING_PID)。重複実行を防止してスキップします。" >> "$LOG_FILE"
        echo "⚠️  [AIVICE] 既に実行中です (PID: $EXISTING_PID)。スキップします。" >&2
        exit 1
    fi
    rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"
trap "rm -f '$LOCK_FILE'" EXIT INT TERM

echo "" >> "$LOG_FILE"
echo "===== [AIVICE] 実行開始: $(date '+%Y-%m-%d %H:%M:%S') (PID: $$) =====" >> "$LOG_FILE"
"$PYTHON" generate_lite.py --blog workup-ai --count 1 --yes >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
echo "===== [AIVICE] 記事生成終了: $(date '+%Y-%m-%d %H:%M:%S') / exit=$EXIT_CODE =====" >> "$LOG_FILE"

if [ "$EXIT_CODE" -ne 0 ]; then
    echo "❌ [AIVICE] エラー終了 (exit=$EXIT_CODE) — $LOG_FILE を確認してください。" >&2
fi
