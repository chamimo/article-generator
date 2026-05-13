#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BLOGS=(
  "workup-ai"
  "ys-trend"
  "hapipo8"
  "kaerudoko"
  "hataraku"
  "hida-no-omoide"
  "web-study1"
)

LIMIT="${1:-3}"
LOG_DIR="$ROOT/output"
LOG_FILE="$LOG_DIR/codex_eyecatch_$(date +%Y%m%d).txt"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "usage: ./run_codex_eyecatch_all.sh [limit_per_blog]"
  echo "未設定の場合は各ブログ最大3件の未設定下書きを処理します。"
  exit 0
fi

mkdir -p "$LOG_DIR"
cd "$ROOT"

echo "===== [CODEX EYECATCH] 巡回開始: $(date '+%Y-%m-%d %H:%M:%S') / limit=$LIMIT =====" >> "$LOG_FILE"

for blog in "${BLOGS[@]}"; do
  echo "----- [$blog] start: $(date '+%Y-%m-%d %H:%M:%S') -----" >> "$LOG_FILE"
  ./run_codex_eyecatch.sh --blog "$blog" --limit "$LIMIT" >> "$LOG_FILE" 2>&1 || true
  echo "----- [$blog] end: $(date '+%Y-%m-%d %H:%M:%S') -----" >> "$LOG_FILE"
done

echo "===== [CODEX EYECATCH] 巡回終了: $(date '+%Y-%m-%d %H:%M:%S') =====" >> "$LOG_FILE"
