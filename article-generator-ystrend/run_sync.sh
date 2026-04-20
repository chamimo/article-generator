#!/bin/bash
# SEO順位同期スクリプト
# cron から呼び出される: 0 6 * * *
#   記事生成（5・11・20時）の1時間後に実行

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"
PYTHON="/opt/homebrew/bin/python3"

PROJECT_DIR="/Users/yama/article-generator-hataraku"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/log_$(date +%Y%m%d).txt"

cd "$PROJECT_DIR" || exit 1

echo "----- 順位同期開始: $(date '+%Y-%m-%d %H:%M:%S') -----" >> "$LOG_FILE"
"$PYTHON" sync_ranks.py --site hataraku >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
echo "----- 順位同期終了: $(date '+%Y-%m-%d %H:%M:%S') / exit=$EXIT_CODE -----" >> "$LOG_FILE"
