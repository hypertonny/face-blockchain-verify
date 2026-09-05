#!/usr/bin/env bash
# One-command end-to-end run (use this for the screen recording).
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv 2>/dev/null || true
. .venv/bin/activate
pip install -q -r requirements.txt
python3 pipeline.py --image "${1:-samples/elon_musk.jpg}" --out out
