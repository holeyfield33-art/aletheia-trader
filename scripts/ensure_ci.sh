#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-/workspaces/aletheia-trader/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  exit 1
fi

echo "[1/5] Ruff"
"$PYTHON_BIN" -m ruff check .

echo "[2/5] Black"
"$PYTHON_BIN" -m black --check .

echo "[3/5] Isort"
"$PYTHON_BIN" -m isort --check-only .

echo "[4/5] Mypy"
"$PYTHON_BIN" -m mypy agents api audit backtesting brokers dashboard risk scripts

echo "[5/5] Pytest"
"$PYTHON_BIN" -m pytest -q

echo "CI-equivalent checks passed."
