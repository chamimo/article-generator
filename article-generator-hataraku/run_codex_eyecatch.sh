#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/opt/homebrew/bin/python3"

cd "$ROOT"
"$PYTHON" codex_eyecatch.py "$@"
