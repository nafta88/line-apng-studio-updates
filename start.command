#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
if [ ! -x ".venv/bin/python" ]; then
  echo "初回セットアップを実行します…"
  ./setup.command
fi
exec .venv/bin/python app.py

