#!/usr/bin/env bash
set -euo pipefail

if [[ ! -d venv ]]; then
  python -m venv venv
fi

source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
streamlit run dashboard/app_enhanced.py
