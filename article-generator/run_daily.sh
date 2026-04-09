#!/bin/bash
# 毎日自動記事生成スクリプト
# cron から呼び出される: 0 5 * * *

# Homebrew の Python を cron 環境でも使えるようにする
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"
PYTHON="/opt/homebrew/bin/python3"

PROJECT_DIR="/Users/yama/article-generator"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/log_$(date +%Y%m%d).txt"

cd "$PROJECT_DIR" || exit 1

echo "===== 実行開始: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG_FILE"

# ── 記事生成・投稿（generate_lite.py：マルチブログ対応・重複防止・画像生成付き）──
"$PYTHON" generate_lite.py >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "===== 記事生成終了: $(date '+%Y-%m-%d %H:%M:%S') / exit=$EXIT_CODE =====" >> "$LOG_FILE"

# ── SEO順位同期（Serposcope → スプレッドシート）──
echo "----- 順位同期開始: $(date '+%Y-%m-%d %H:%M:%S') -----" >> "$LOG_FILE"
"$PYTHON" sync_ranks.py --site workup-ai >> "$LOG_FILE" 2>&1
RANK_EXIT=$?
echo "----- 順位同期終了: $(date '+%Y-%m-%d %H:%M:%S') / exit=$RANK_EXIT -----" >> "$LOG_FILE"

echo "===== 全処理終了: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG_FILE"
