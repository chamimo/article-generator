#!/bin/bash
# 毎日自動記事生成スクリプト
# cron から呼び出される: 0 5,11,20 * * *
#   5時・11時・20時 に各1記事生成
#   SEO順位同期は朝5時の実行時のみ行う

# Homebrew の Python を cron 環境でも使えるようにする
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"
PYTHON="/opt/homebrew/bin/python3"

PROJECT_DIR="/Users/yama/article-generator-hataraku"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/log_$(date +%Y%m%d).txt"

cd "$PROJECT_DIR" || exit 1

echo "===== [HATARAKU] 実行開始: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG_FILE"

# ── 記事生成・投稿（1記事/回）──
"$PYTHON" generate_lite.py --blog hataraku --count 1 --yes >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "===== [HATARAKU] 記事生成終了: $(date '+%Y-%m-%d %H:%M:%S') / exit=$EXIT_CODE =====" >> "$LOG_FILE"
