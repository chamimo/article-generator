#!/bin/bash
# 毎日自動記事生成スクリプト
# cron から呼び出される: 0 5 * * *

PROJECT_DIR="/Users/yama/article-generator"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/log_$(date +%Y%m%d).txt"

cd "$PROJECT_DIR" || exit 1

# .env を読み込む
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
fi

echo "===== 実行開始: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG_FILE"

python3 main.py --clusters --limit 5 >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "===== 実行終了: $(date '+%Y-%m-%d %H:%M:%S') / exit=$EXIT_CODE =====" >> "$LOG_FILE"
