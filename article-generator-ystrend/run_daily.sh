#!/bin/bash
# ワイズトレンド (ys-trend.com) 毎日自動記事生成
# cron: 0 5,11,20 * * *

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"
PYTHON="/opt/homebrew/bin/python3"

PROJECT_DIR="/Users/yama/article-generator-ystrend"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/log_$(date +%Y%m%d).txt"

cd "$PROJECT_DIR" || exit 1

echo "===== [YSTREND] 実行開始: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG_FILE"
"$PYTHON" generate_lite.py --blog ys-trend --count 1 --yes >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
echo "===== [YSTREND] 記事生成終了: $(date '+%Y-%m-%d %H:%M:%S') / exit=$EXIT_CODE =====" >> "$LOG_FILE"
