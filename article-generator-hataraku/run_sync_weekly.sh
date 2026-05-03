#!/bin/bash
# 全ブログ SEO順位週次同期 + 順位下落フラグチェック
# cron: 0 6 * * 0  (毎週日曜 6:00)
# 実行: bash run_sync_weekly.sh [--dry-run]

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"
PYTHON="/opt/homebrew/bin/python3"
PROJECT_DIR="/Users/yama/article-generator-hataraku"
LOG_DIR="$PROJECT_DIR/output"
DATE=$(date +%Y%m%d)
DRY_RUN="${1:-}"

SITES=(hataraku workup-ai ys-trend kaerudoko hapipo8 hida-no-omoide web-study1)

cd "$PROJECT_DIR" || exit 1

SUMMARY_LOG="$LOG_DIR/sync_weekly_${DATE}.log"
echo "===== 週次順位同期開始: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$SUMMARY_LOG"

# ── 1. 順位データ同期 ──
for SITE in "${SITES[@]}"; do
    echo "" >> "$SUMMARY_LOG"
    echo "----- [sync/$SITE] 開始: $(date '+%H:%M:%S') -----" >> "$SUMMARY_LOG"
    if [ "$DRY_RUN" = "--dry-run" ]; then
        "$PYTHON" sync_ranks.py --site "$SITE" --dry-run >> "$SUMMARY_LOG" 2>&1
    else
        "$PYTHON" sync_ranks.py --site "$SITE" >> "$SUMMARY_LOG" 2>&1
    fi
    EXIT_CODE=$?
    echo "----- [sync/$SITE] 終了: $(date '+%H:%M:%S') / exit=$EXIT_CODE -----" >> "$SUMMARY_LOG"
    sleep 5
done

echo "" >> "$SUMMARY_LOG"
echo "===== 順位同期完了 / フラグチェック開始: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$SUMMARY_LOG"

# ── 2. 順位下落フラグチェック ──
for SITE in "${SITES[@]}"; do
    echo "" >> "$SUMMARY_LOG"
    echo "----- [flag/$SITE] 開始: $(date '+%H:%M:%S') -----" >> "$SUMMARY_LOG"
    if [ "$DRY_RUN" = "--dry-run" ]; then
        "$PYTHON" check_rank_drop.py --site "$SITE" --dry-run >> "$SUMMARY_LOG" 2>&1
    else
        "$PYTHON" check_rank_drop.py --site "$SITE" >> "$SUMMARY_LOG" 2>&1
    fi
    EXIT_CODE=$?
    echo "----- [flag/$SITE] 終了: $(date '+%H:%M:%S') / exit=$EXIT_CODE -----" >> "$SUMMARY_LOG"
    sleep 3
done

echo "" >> "$SUMMARY_LOG"
echo "===== 週次処理完了: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$SUMMARY_LOG"
