#!/bin/zsh
set -eu
cd -- "${0:A:h}"

if ! xcode-select -p >/dev/null 2>&1; then
  print -u2 '터미널에서 xcode-select --install을 실행해 Command Line Tools를 설치하세요.'
  exit 1
fi
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  print -u2 'Python 3.10 이상을 설치하세요.'
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if [[ ! -f .venv/requirements.lock || requirements.txt -nt .venv/requirements.lock ]]; then
  .venv/bin/python -m pip install -r requirements.txt
  cp requirements.txt .venv/requirements.lock
fi
if [[ ! -x vision-ocr || vision.swift -nt vision-ocr ]]; then
  mkdir -p .swift-cache
  xcrun swiftc -suppress-warnings -module-cache-path "$PWD/.swift-cache" vision.swift -o vision-ocr
fi
exec .venv/bin/python server.py --bind 0.0.0.0 "$@"
