#!/usr/bin/env bash
# Full record-ready demo: pipeline -> verified on-chain record -> verification.
set -euo pipefail
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
rm -rf out_demo
printf '$ fbv run --image samples/elon_musk.jpg --out out_demo --chain auto\n'
"$PY" fbv.py run --image samples/elon_musk.jpg --out out_demo --chain auto
SIG=$("$PY" -c "import json; print(json.load(open('out_demo/tx.json'))['signature'])")
printf '\n$ fbv verify --tx %s --record out_demo/record.json\n' "$SIG"
"$PY" fbv.py verify --tx "$SIG" --record out_demo/record.json
