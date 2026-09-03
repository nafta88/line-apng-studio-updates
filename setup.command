#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "Python 3をインストールします…"
    brew install python
  else
    echo "Python 3が見つかりません。Python 3をインストールしてから再実行してください。"
    exit 1
  fi
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "FFmpegをインストールします…"
    brew install ffmpeg
  else
    echo "FFmpegが見つかりません。Homebrewをインストール後、brew install ffmpeg を実行してください。"
    exit 1
  fi
fi

python3 -m venv .venv
.venv/bin/python -m pip --isolated install \
  --disable-pip-version-check \
  --no-input \
  --only-binary=:all: \
  --index-url https://pypi.org/simple \
  -r requirements.txt
echo "セットアップ完了。start.command をダブルクリックしてください。"
