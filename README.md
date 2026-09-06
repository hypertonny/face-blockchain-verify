# Face ID + Blockchain Verification

Detect and encode a face from a photo, find a **real matching social-media
post via genuine live reverse-image search**, face-verify it is the **same
face**, and write the match to a **blockchain as a tamper-evident,
verifiable record**.

No website, no hosting — the pipeline itself is the deliverable.

## Contents

- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Setup](#setup)
- [Usage](#usage)
- [Which blockchain, and why Solana](#which-blockchain-and-why-solana)
- [Requirement coverage](#requirement-coverage)
- [Accuracy](#accuracy)
- [Testing](#testing)
- [Screen recording](#screen-recording)
- [Project structure](#project-structure)
- [Known limitations](#known-limitations)

## How it works

```
input photo (file or URL)
  │ 1. face.py — detect largest face → 512-d ArcFace embedding (InsightFace)
  ▼
face embedding + bounding box + sha256
  │ 2. reverse_search.py — publish to a temp public URL if local, then a LIVE
  │    reverse-image query of the FULL image and the FACE CROP
  │    (SerpApi Google Lens if SERPAPI_API_KEY is set, else Yandex CBIR).
  │    Nothing is hardcoded; every match comes from the live index.
  ▼
  │ 3. match_verify.py — download each social candidate's photo, re-encode
  │    its face, keep only matches showing the SAME face (cosine similarity
  │    ≥ threshold, default 0.45). Candidates are ranked by similarity.
  ▼
verified real social-media post (title, post URL, similarity score)
  │ 4. blockchain.py / stellar.py — SHA-256 of the canonical record is
  │    written as a Solana devnet Memo (primary) or Stellar testnet
  │    ManageData (automatic fallback). Immutable once confirmed.
  ▼
out/record.json + out/matches.json + out/tx.json + public explorer URL
```

Only hashes and the match's public post URL ever go on-chain — never the
photo, never the embedding.

## Architecture

| Module | Responsibility | Key detail |
|---|---|---|
| `pipeline.py` | Orchestrates the 5 steps; CLI flags; final result summary | SSRF guard on URL inputs, `--no-upload` privacy mode, `--strict-social` judging mode |
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

```bash
# Full pipeline: face → live search → face-verify → on-chain record
python pipeline.py --image samples/elon_musk.jpg --out out

# Any local photo or public URL
python pipeline.py --image /path/to/photo.jpg --out out
python pipeline.py --image https://example.com/photo.jpg --out out

# Judging mode: exit non-zero unless a FACE-VERIFIED social match exists
python pipeline.py --image photo.jpg --out out --strict-social --threshold 0.45

# Privacy mode: never publish local files (URL inputs only)
python pipeline.py --image https://example.com/photo.jpg --out out --no-upload

# Face + search only (no chain write, no funds needed)
python pipeline.py --image photo.jpg --out out --skip-chain

# Choose chain explicitly (default auto = solana → stellar → polygon if configured)
python pipeline.py --image photo.jpg --out out --chain solana
python pipeline.py --image photo.jpg --out out --chain stellar
python pipeline.py --image photo.jpg --out out --chain polygon  # needs POLYGON_REGISTRY

# Deploy the Polygon registry yourself (you sign locally — key never leaves your machine):
# 1. fund 0xYOUR_ADDRESS at https://faucet.polygon.technology/ (Amoy)
# 2. export POLYGON_PRIVATE_KEY="0x..."   # local shell only, never commit
# 3. python deploy_polygon.py             # prints contract + explorer link
# 4. export POLYGON_REGISTRY="0x..."      # then --chain polygon works

# Re-verify any record against its on-chain data, any time later
python verify.py --tx <signature> --record out/record.json

# Accuracy benchmark (needs samples/groundtruth.json + local photos)
python bench.py

# One-command run (use for the screen recording)
bash run.sh samples/elon_musk.jpg
# Full record-ready session (pipeline + verify chained)
bash demo_run.sh
```

Each run prints per-step timings, a ranked candidate table
(`VERIFIED`/`rejected` + similarity + domain + post URL), and a final
result box with the explorer link and the exact `verify.py` command.

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
`deploy_polygon.py`). `FaceVerifyRegistry.anchor(recordHash, matchUrl)`
stores the 32-byte record digest + post URL; first write wins. Deploy with
`python deploy_polygon.py` (you sign locally), then
`--chain polygon`. Verify at `https://amoy.polygonscan.com/tx/<hash>`.

## Requirement coverage

| Briefing requirement | Implementation | Evidence |
|---|---|---|
| Detect + encode a face, any library | `face.py` — InsightFace ArcFace 512-d (+3 fallback tiers) | `face_crop.jpg`, `embedding_sha256` in `record.json` |
| Real matching social post, genuine reverse-image search, no hardcoding | `reverse_search.py` — live SerpApi Lens / Yandex CBIR, full + crop; `match_verify.py` cosine check | `matches.json`; `verified_match` + `similarity`; `ACCURACY.md` 5/5 top-1 |
| Tamper-evident verifiable blockchain record | `blockchain.py` Solana memo / `stellar.py` ManageData | explorer URL in `tx.json`; `verify.py` → MATCH |
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
python -m pytest -m "not network" -q   # 10 offline unit tests
python -m pytest -q                    # + 3 live network tests
```

Offline: parser strictness, social filter, cosine math, SSRF refusals,
keypair-path safety, memo-tx byte structure, hash determinism, tamper
detection. Network: our hand-rolled Solana tx must behave **byte-identical
to `solders`** on devnet simulate (this test once caught a real missing
signature-count byte), live Yandex search returns matches, Horizon testnet
reachable. CI runs the offline suite on every push (`.github/workflows/ci.yml`).

## Screen recording

Record one unedited terminal session (OBS / gnome-screencast / screen
capture) running:

```bash
bash demo_run.sh
```

It runs the full pipeline on the sample (face → live search → verified
ranking → on-chain confirmation → result box) then chains the exact
`verify.py` command with the real signature, ending in MATCH. Nothing to
edit out — one command, one take.

## Project structure

```
pipeline.py  reverse_search.py  match_verify.py  face.py
blockchain.py  stellar.py  verify.py  bench.py
tests/  samples/ (elon_musk.jpg tracked; personal test photos git-ignored)
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
