#!/bin/bash
# 自動バックアップスクリプト
# cron から呼び出される: 30 5 * * *（記事生成の30分後）

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"

PROJECT_DIR="/Users/yama/article-generator-aivice"
GIT_ROOT="/Users/yama"
LOG_DIR="$PROJECT_DIR/output"
LOG_FILE="$LOG_DIR/log_$(date +%Y%m%d).txt"

cd "$GIT_ROOT" || exit 1

echo "----- バックアップ開始: $(date '+%Y-%m-%d %H:%M:%S') -----" >> "$LOG_FILE"

# 変更があるか確認
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard article-generator-aivice/)" ]; then
    echo "----- バックアップ: 変更なし / スキップ -----" >> "$LOG_FILE"
    exit 0
fi

git add article-generator-aivice/ >> "$LOG_FILE" 2>&1

COMMIT_MSG="自動バックアップ $(date '+%Y-%m-%d')"
git commit -m "$COMMIT_MSG" >> "$LOG_FILE" 2>&1
COMMIT_EXIT=$?

if [ $COMMIT_EXIT -eq 0 ]; then
    git push >> "$LOG_FILE" 2>&1
    PUSH_EXIT=$?
    echo "----- バックアップ完了: exit=$PUSH_EXIT -----" >> "$LOG_FILE"
else
    echo "----- バックアップ: コミットなし / スキップ -----" >> "$LOG_FILE"
fi
