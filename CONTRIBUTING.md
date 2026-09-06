# Contributing

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Before opening a pull request

```bash
fbv --help
python -m pytest -m "not network" -q
```

Network tests consume third-party quotas and testnet resources; run them only
when needed:

```bash
python -m pytest -q
```

## Rules

- Never commit API keys, private keys, `out/`, or personal test photos.
- Keep default CLI output concise; add diagnostic data behind `--verbose`.
- Keep on-chain records limited to a canonical record hash and public match
  URL. Never put a photo or biometric embedding on-chain.
- Add offline tests for behavior changes.
