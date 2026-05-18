#!/bin/bash
# リライト実行スクリプト
# 「リライト提案」シートの「リライト実行」列が「now」の記事をリライトし、
# WordPress に下書き保存する。
#
# 使い方:
#   ./run_rewrite.sh workup-ai      # AIVice
#   ./run_rewrite.sh hataraku       # はた楽ナビ

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin"
PYTHON="/opt/homebrew/bin/python3"
PROJECT_DIR="/Users/yama/article-generator-hataraku"

BLOG="${1:-workup-ai}"

cd "$PROJECT_DIR" || exit 1

"$PYTHON" - "$BLOG" <<'PYEOF'
import sys, os
blog = sys.argv[1]
os.chdir(os.path.dirname(os.path.abspath(__file__)) if os.path.isfile(__file__) else '.')
sys.path.insert(0, '/Users/yama/article-generator-hataraku')
from dotenv import load_dotenv
load_dotenv('/Users/yama/article-generator-hataraku/.env')
from modules.rewrite_executor import run_rewrite
run_rewrite(blog)
PYEOF
