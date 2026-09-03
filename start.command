#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"
REQ_HASH="$(shasum -a 256 requirements.txt | awk '{print $1}')"
INSTALLED_HASH=""
if [ -f ".venv/.requirements-sha256" ]; then
  INSTALLED_HASH="$(tr -d '\r\n' < .venv/.requirements-sha256)"
fi
if [ ! -x ".venv/bin/python" ] || [ "$REQ_HASH" != "$INSTALLED_HASH" ]; then
  echo "必要な部品を安全に確認・更新します…"
  ./setup.command
fi
exec .venv/bin/python app.py
