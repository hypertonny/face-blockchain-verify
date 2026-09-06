# Face ID + Blockchain Verification

![CI](https://github.com/hypertonny/face-blockchain-verify/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)

A privacy-conscious CLI pipeline that detects and encodes a face, finds a real
matching social-media post through live reverse-image search, verifies the
same face is present, and anchors a tamper-evident record on-chain.

No website or hosted service is required. The pipeline is the deliverable.

## Quick Start

```bash
git clone https://github.com/hypertonny/face-blockchain-verify.git
cd face-blockchain-verify
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install -e .

# Configure keys in your shell. Never commit them.
export SERPAPI_API_KEY="..."
export SOLANA_RPC_URL="https://devnet.helius-rpc.com/?api-key=..."

fbv run --image samples/elon_musk.jpg --out out --strict-social
```

The first run downloads the InsightFace models. Subsequent runs reuse the
cached models. Use `NO_COLOR=1` for plain output in CI or log files.

## CLI Commands

| Command | Purpose |
|---|---|
| `fbv run` | Full face → live search → same-face verification → blockchain pipeline |
| `fbv verify` | Recompute the record hash and verify it against chain data |
| `fbv bench` | Measure search recall and similarity ranking on ground truth |
| `fbv deploy` | Deploy `FaceVerifyRegistry` to Polygon Amoy; signs locally |
| `fbv compile` | Compile the Solidity registry to ABI + bytecode |

Every command supports `--help` and `--version`. The original direct scripts
(`python pipeline.py`, `python verify.py`, etc.) remain available.

### Common Commands

```bash
# Full verification; fail unless same-face social match exists
fbv run --image samples/image-1.png --out out --strict-social

# Use the deployed Polygon registry
fbv run --image samples/image-1.png --out out \
  --chain polygon --strict-social

# Inspect a record later
fbv verify --tx 0xTRANSACTION_HASH --record out/record.json

# Five-photo accuracy benchmark
fbv bench --groundtruth samples/groundtruth.json

# Polygon Amoy contract deployment
export POLYGON_PRIVATE_KEY="0x..."       # local only
fbv deploy
export POLYGON_REGISTRY="0xDEPLOYED_ADDRESS"

# Run offline unit tests
python -m pytest -m "not network" -q
```

## Output

Default output is intentionally short and scan-friendly:

```text
fbv run samples/image-1.png → out
[1/4] Face — detect + encode
       insightface-buffalo_s · 512-d · bbox [...] · score 0.88
[2/4] Search — live reverse-image search (full + face crop)
       serpapi-google-lens · 112 matches · 5 social
[3/4] Verify — face-check top 5 social candidates
       ✓ 0.9687  x.com       https://x.com/...
       5/5 same-face verified
[4/4] Chain — anchor record (polygon)
       ✓ polygon-amoy · CONFIRMED

✓ VERIFIED SAME-FACE MATCH
       post     https://x.com/...
       sim      0.9687 (threshold 0.45)
       explorer https://amoy.polygonscan.com/tx/...
       verify   fbv verify --tx ... --record out/record.json
```

Use `-v` / `--verbose` for hashes, published URLs, timing details, and
provider diagnostics. Colors activate on TTY and can be disabled with
`NO_COLOR=1`.

## Architecture


| Module | Responsibility | Key detail |
|---|---|---|
| `fbv.py` + `ui.py` + `cliutil.py` | Unified CLI (`fbv run/verify/bench/deploy/compile`), TTY-aware colors, `--version`, examples, exit codes | Colors off when piped or `NO_COLOR=1`; usage errors exit 2 with hints |
| `pipeline.py` | Orchestrates the 4 steps; CLI flags; final result summary | Parallel full+crop search and candidate verification; SSRF guard; `--no-upload`; `--strict-social`; `-v` verbose |
| `face.py` | Face detection + encoding, tiered backends | Tier 1: InsightFace ArcFace 512-d · Tier 2: ONNX ArcFace · Tier 3: YuNet+SFace 128-d · Tier 4: offline pixel fallback |
| `reverse_search.py` | Genuine live reverse-image search | SerpApi Google Lens (`engine=google_lens`, `type=all`) or keyless Yandex CBIR `cbir_page=sites`; full image + face crop; social-domain filter |
| `match_verify.py` | Proves the hit shows the same face | Downloads candidate photo (full image → thumbnail fallback), cosine similarity vs threshold |
| `blockchain.py` | Solana devnet memo writer (pure Python: `base58`+`pynacl`) | Hand-rolled legacy tx proven byte-equivalent to `solders`; tested against devnet simulate |
| `stellar.py` | Stellar testnet fallback writer (`stellar-sdk`) | Record hash + post URL in `ManageData` ops, funded via open Friendbot faucet |
| `contracts/FaceVerifyRegistry.sol` | Polygon registry: `anchor(recordHash, matchUrl)` + `get` + event | Stores hash only; first write wins; 1.6 KB bytecode |
| `polygon.py` / `deploy_polygon.py` | Anchor to / deploy on Polygon Amoy (`web3`) | Deploy script signs locally with your key; key never leaves your machine |
| `verify.py` | Independent re-verification (all three chains) | Recomputes canonical SHA-256, compares with on-chain data → MATCH / MISMATCH |
| `bench.py` | Accuracy benchmark over `samples/groundtruth.json` | Reports recall, top-1 by similarity, best similarity per case |

## Setup

Prerequisites: **Python 3.14** (3.10+ works), `pip`, ~500 MB free (face models
download once on first run).

```bash
git clone https://github.com/hypertonny/face-blockchain-verify.git
cd face-blockchain-verify
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt   # pinned versions
```

API keys (env only — never committed, never logged; see `.env.example`):

```bash
# cp .env.example ~/.fbv_keys   # then fill in, chmod 600, and:
source ~/.fbv_keys
```

| Variable | Required? | Purpose |
|---|---|---|
| `SERPAPI_API_KEY` | Recommended | Genuine Google Lens (`type=all`: exact + visual matches). Without it, keyless Yandex CBIR is used. Free 250 searches/month. |
| `SOLANA_RPC_URL` | Recommended | Solana RPC, e.g. `https://devnet.helius-rpc.com/?api-key=KEY`. Defaults to the public devnet endpoint (rate-limited). |
| `POLYGON_RPC_URL` | Optional | Polygon Amoy RPC (default: public endpoint). |
| `POLYGON_REGISTRY` | For `--chain polygon` | Deployed `FaceVerifyRegistry` address (from `deploy_polygon.py`). |
| `POLYGON_PRIVATE_KEY` | For Polygon writes | Anchor/deployer key — local env only, never committed or logged. Reads need no key. |
| `FBV_SKIP_MODEL_DOWNLOAD=1` | No | Skip the ArcFace bundle; use the offline fallback backend. |

## Usage

All commands run through the unified `fbv` CLI (`pip install -e .` exposes
it on PATH; otherwise use `python fbv.py …`).

```bash
# Full pipeline: face → live search → face-verify → on-chain record
fbv run --image samples/elon_musk.jpg --out out

# Any local photo or public URL
fbv run --image /path/to/photo.jpg --out out
fbv run --image https://example.com/photo.jpg --out out

# Judging mode: exit non-zero unless a FACE-VERIFIED social match exists
fbv run --image photo.jpg --out out --strict-social --threshold 0.45

# Privacy mode: never publish local files (URL inputs only)
fbv run --image https://example.com/photo.jpg --out out --no-upload

# Extra detail (hashes, timings, published URLs, provider diagnostics)
fbv run --image photo.jpg --out out -v

# Face + search only (no chain write, no funds needed)
fbv run --image photo.jpg --out out --skip-chain

# Choose chain explicitly (default auto = solana → polygon if configured → stellar)
fbv run --image photo.jpg --out out --chain solana
fbv run --image photo.jpg --out out --chain stellar
fbv run --image photo.jpg --out out --chain polygon  # needs POLYGON_REGISTRY

# Deploy the Polygon registry yourself (you sign locally — key never leaves your machine):
# 1. fund 0xYOUR_ADDRESS at https://faucet.polygon.technology/ (Amoy)
# 2. export POLYGON_PRIVATE_KEY="0x..."   # local shell only, never commit
# 3. fbv deploy                           # prints contract + explorer link
# 4. export POLYGON_REGISTRY="0x..."      # then --chain polygon works

# Re-verify any record against its on-chain data, any time later
fbv verify --tx <signature> --record out/record.json

# Accuracy benchmark (needs samples/groundtruth.json + local photos)
fbv bench

# Compile the registry contract
fbv compile

# One-command run (use for the screen recording)
bash run.sh samples/elon_musk.jpg
# Full record-ready session (pipeline + verify chained)
bash demo_run.sh
```

Each command supports `--help` and `--version`. Colors activate on TTY and
can be disabled with `NO_COLOR=1`. Exit codes: `0` success/MATCH,
`1` runtime failure or MISMATCH, `2` usage error.

Each run prints step progress, a ranked candidate table
(`VERIFIED`/`rejected` + similarity + domain + post URL), and a final
summary with the explorer link and the exact `fbv verify` command.

Artifacts in `out/`: `record.json` (canonical record + `record_sha256` +
verification), `matches.json` (ranked live matches), `tx.json` (signature +
explorer URL), `face_crop.jpg`, `id.json` / `stellar.json` (auto-generated
keypairs — `0600`, git-ignored, keep secret).

## Which blockchain, and why Solana

**Primary: Solana devnet.** Sub-cent fees and ~400 ms slots make per-case
memo writes effectively free and fast; the **native Memo program**
(`MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`) stores arbitrary bytes with
no contract to deploy or audit; any judge verifies via the explorer link
with no node or key. Override the RPC with `SOLANA_RPC_URL`.

**Where Helius is used:** Helius is the **RPC provider + faucet**, nothing
more. Every chain call in `blockchain.py` — `getLatestBlockhash`,
`requestAirdrop`, `sendTransaction`, `getSignatureStatuses`,
`getTransaction` — goes through `SOLANA_RPC_URL`
(`https://devnet.helius-rpc.com/?api-key=KEY`). The default public endpoint
works but is aggressively rate-limited (including a ~1 SOL/day/project
faucet cap); Helius raises those limits and lands transactions over staked
connections.

**Automatic fallback: Stellar testnet** (`stellar.py`). If the Solana faucet
is throttled, the pipeline funds a fresh account via the open Friendbot
faucet and stores the record SHA-256 (+ post URL) in `ManageData`
operations. Verify at `https://stellar.expert/explorer/testnet/tx/<hash>`.

**Your own contract: Polygon Amoy** (`contracts/`, `polygon.py`,
`deploy_polygon.py`). `FaceVerifyRegistry.anchor(recordHash, matchUrl,
prevHash)` stores the 32-byte record digest + post URL **linked to your
previous record hash** — every new task extends the chain, and a wrong
`prevHash` reverts on-chain. Deploy with `fbv deploy` (you sign locally),
then `--chain polygon`. The pipeline reads your latest hash automatically —
just set `POLYGON_REGISTRY` once. Verify at
`https://amoy.polygonscan.com/tx/<hash>`.

## Requirement coverage

| Briefing requirement | Implementation | Evidence |
|---|---|---|
| Detect + encode a face, any library | `face.py` — InsightFace ArcFace 512-d (+3 fallback tiers) | `face_crop.jpg`, `embedding_sha256` in `record.json` |
| Real matching social post, genuine reverse-image search, no hardcoding | `reverse_search.py` — live SerpApi Lens / Yandex CBIR, full + crop; `match_verify.py` cosine check | `matches.json`; `verified_match` + `similarity`; `ACCURACY.md` 5/5 top-1 |
| Tamper-evident verifiable blockchain record | `blockchain.py` Solana memo / `polygon.py` registry anchor / `stellar.py` ManageData | explorer URL in `tx.json`; `fbv verify` → MATCH |
| No website or hosting | Pipeline + tests only | — |
| Source: functionality, run, chain, limitations | This README + `ACCURACY.md` | — |
| Unedited screen recording | `bash demo_run.sh` in one take | Your capture (script prints everything needed) |

## Accuracy

Measured with face-verification on (cosine, threshold 0.45). Full table in
[`ACCURACY.md`](ACCURACY.md): **recall 5/5, top-1 by similarity 5/5** on the
user-confirmed ground-truth set (Lens, full+crop, 512-d). The pipeline also
correctly rejects lookalikes (e.g. 0.14 / 0.005 similarities). Reference
run: Elon sample → x.com post, similarity **0.9687**, Stellar tx
`95de4c44…0df2e`, verify MATCH.

## Testing

```bash
python -m pytest -m "not network" -q   # 19 offline unit tests
python -m pytest -q                    # + 3 live network tests
```

Offline: parser strictness, social filter, cosine math, SSRF refusals,
keypair-path safety, memo-tx byte structure, hash determinism, tamper
detection, local-chain contract lifecycle, CLI conformance (`--version`,
prog names, exit codes, `fbv` dispatcher). Network: our hand-rolled Solana
tx must behave **byte-identical to `solders`** on devnet simulate (this test
once caught a real missing signature-count byte), live Yandex search returns
matches, Horizon testnet reachable. CI runs the offline suite on every push
(`.github/workflows/ci.yml`).

## Screen recording

Record one unedited terminal session (OBS / gnome-screencast / screen
capture) running:

```bash
bash demo_run.sh
```

It runs the full pipeline on the sample (face → live search → verified
ranking → on-chain confirmation → result box) then chains the exact
`fbv verify` command with the real signature, ending in MATCH. Nothing to
edit out — one command, one take.

## Project structure

```
fbv.py  ui.py  cliutil.py  pyproject.toml  LICENSE  CONTRIBUTING.md
pipeline.py  reverse_search.py  match_verify.py  face.py
blockchain.py  stellar.py  polygon.py  deploy_polygon.py  verify.py  bench.py
contracts/  tests/  samples/ (elon_musk.jpg tracked; personal test photos git-ignored)
run.sh  demo_run.sh  requirements.txt (pinned)  pytest.ini
.github/workflows/ci.yml  README.md  ACCURACY.md  .env.example
```

## Known limitations

- **Face recognition ≠ identity proof.** Embedding + similarity prove the
  *same face* appears in both photos, not legal identity.
- **Reverse search needs public indexes.** Fresh/private photos may yield zero
  social matches — `--strict-social` then exits 2 instead of recording weak
  evidence. Live indexes also shift: provider result order varies run to run
  (why we re-rank by face similarity).
- **Local files need a temporary public URL** (catbox.moe / tmpfiles.org) so
  the CBIR engine can fetch bytes — unless `--no-upload` with URL input. The
  hashed bytes are always the local original.
- **Solana devnet is a test network** (resettable, no mainnet value) and its
  faucet is rate-limited; the pipeline fails over to Stellar automatically.
- **Keyless Yandex parsing is fragile** (page layouts change); SerpApi Lens
  is the stable path.
- **Privacy.** Only hashes + the public post URL go on-chain — but
  reverse-searching someone else's photo without consent may violate platform
  ToS / local law. Use your own photos or public-figure samples.
