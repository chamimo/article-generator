#!/bin/bash
# 記事生成スクリプト（全ブログ共通）
# 使い方:
#   ./run_daily.sh              # hataraku（デフォルト）
#   ./run_daily.sh hapipo8      # 指定ブログ
#   ./run_daily.sh kaerudoko
#   ./run_daily.sh web-study1

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"
PYTHON="/opt/homebrew/bin/python3"

BLOG="${1:-hataraku}"
PROJECT_DIR="/Users/yama/article-generator-hataraku"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/${BLOG}_$(date +%Y%m%d).txt"

cd "$PROJECT_DIR" || exit 1

echo "===== [$(echo "$BLOG" | tr '[:lower:]' '[:upper:]')] 実行開始: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG_FILE"
"$PYTHON" generate_lite.py --blog "$BLOG" --count 1 --yes >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
echo "===== [$(echo "$BLOG" | tr '[:lower:]' '[:upper:]')] 記事生成終了: $(date '+%Y-%m-%d %H:%M:%S') / exit=$EXIT_CODE =====" >> "$LOG_FILE"
