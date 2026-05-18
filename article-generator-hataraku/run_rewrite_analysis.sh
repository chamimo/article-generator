#!/bin/bash
# GSC分析 → リライト提案シート記入
#
# 使い方:
#   ./run_rewrite_analysis.sh workup-ai        # AIVice
#   ./run_rewrite_analysis.sh hataraku         # はた楽ナビ
#   ./run_rewrite_analysis.sh workup-ai 30     # 最大30件まで提案

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"
PYTHON="/opt/homebrew/bin/python3"
PROJECT_DIR="/Users/yama/article-generator-hataraku"

BLOG="${1:-workup-ai}"
MAX="${2:-20}"

cd "$PROJECT_DIR" || exit 1
"$PYTHON" rewrite_analysis.py "$BLOG" "$MAX"
