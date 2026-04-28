#!/usr/bin/env bash
set -euo pipefail

python scripts/backtest.py
streamlit run dashboard/app.py
