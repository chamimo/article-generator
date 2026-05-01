#!/bin/bash
# 全ブログ かにばりチェック（週次）
# シートの未判定AIMキーワードにかにばり判定を書き込む
# cron: 0 3 * * 0  （毎週日曜 03:00）

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"
PYTHON="/opt/homebrew/bin/python3"

PROJECT_DIR="/Users/yama/article-generator-hataraku"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/kanikabari_$(date +%Y%m%d).txt"

cd "$PROJECT_DIR" || exit 1

echo "===== [KANIKABARI] 開始: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG_FILE"
"$PYTHON" generate_lite.py --kanikabari --yes >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
echo "===== [KANIKABARI] 終了: $(date '+%Y-%m-%d %H:%M:%S') / exit=$EXIT_CODE =====" >> "$LOG_FILE"
