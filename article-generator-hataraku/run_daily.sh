#!/bin/bash
# 記事生成スクリプト（全ブログ共通）
# 使い方:
#   ./run_daily.sh              # hataraku（デフォルト）1記事
#   ./run_daily.sh hapipo8 3    # 指定ブログ・記事数指定
#   ./run_daily.sh kaerudoko 2
#   ./run_daily.sh web-study1 2

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"
PYTHON="/opt/homebrew/bin/python3"

BLOG="${1:-hataraku}"
COUNT="${2:-1}"
PROJECT_DIR="/Users/yama/article-generator-hataraku"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/${BLOG}_$(date +%Y%m%d).txt"

cd "$PROJECT_DIR" || exit 1

LOCK_FILE="$LOG_DIR/.${BLOG}.lock"

# 既に同ブログが実行中なら即終了
if [ -f "$LOCK_FILE" ]; then
    EXISTING_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "⚠️  [${BLOG}] 既に実行中です (PID: $EXISTING_PID)。重複実行を防止してスキップします。" >> "$LOG_FILE"
        echo "⚠️  [${BLOG}] 既に実行中です (PID: $EXISTING_PID)。スキップします。" >&2
        exit 1
    fi
    rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"
trap "rm -f '$LOCK_FILE'" EXIT INT TERM

echo "===== [$(echo "$BLOG" | tr '[:lower:]' '[:upper:]')] 実行開始: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG_FILE"
"$PYTHON" generate_lite.py --blog "$BLOG" --count "$COUNT" --yes >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
echo "===== [$(echo "$BLOG" | tr '[:lower:]' '[:upper:]')] 記事生成終了: $(date '+%Y-%m-%d %H:%M:%S') / exit=$EXIT_CODE =====" >> "$LOG_FILE"
