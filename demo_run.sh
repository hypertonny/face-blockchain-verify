#!/usr/bin/env bash
# Recorded end-to-end demo: face -> live reverse search -> on-chain record -> verify.
set -u
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
rm -rf out_demo
echo "\$ $PY pipeline.py --image samples/elon_musk.jpg --out out_demo --chain auto"
$PY pipeline.py --image samples/elon_musk.jpg --out out_demo --chain auto
SIG=$($PY -c "import json; print(json.load(open('out_demo/tx.json'))['signature'])")
echo
echo "\$ $PY verify.py --tx $SIG --record out_demo/record.json"
$PY verify.py --tx "$SIG" --record out_demo/record.json
