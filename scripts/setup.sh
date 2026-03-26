#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[setup] repo root: $ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[setup][error] python3 is required but was not found"
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "[setup][error] node is required but was not found"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[setup][error] npm is required but was not found"
  exit 1
fi

echo "[setup] python: $(python3 --version)"
echo "[setup] node: $(node --version)"
echo "[setup] npm: $(npm --version)"

echo "[setup] installing node dependencies"
npm install

echo "[setup] installing playwright browser binaries (chromium)"
npx playwright install chromium

echo "[setup] verifying playwright import"
node -e 'console.log("playwright ok:", !!require("playwright").chromium)'

echo "[setup] running python test suite"
python3 -m unittest discover -s tests -p "test_*.py"

echo "[setup] done"
