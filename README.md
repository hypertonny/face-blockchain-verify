# Face ID + Blockchain Verification

Pipeline that **detects + encodes a face** from a photo (ArcFace 512-d),
finds a **real matching social-media post via genuine live reverse-image
search**, **face-verifies** the match (same face, cosine ≥ threshold), and
writes that match to a **blockchain as a tamper-evident, verifiable record**.

No website, no hosting — the pipeline itself is the deliverable.

## How it works

```
input photo
  │  face.py — detect largest face, 512-d ArcFace embedding (InsightFace
  │            buffalo; YuNet+SFace / ONNX / pixel fallbacks if unavailable)
  ▼
face embedding + bbox + sha256
  │  reverse_search.py — publish to temp public URL if local, then LIVE
  │            reverse-image query of FULL image + FACE CROP (SerpApi Google
  │            Lens if SERPAPI_API_KEY is set, else Yandex CBIR sites index).
  │            Nothing is hardcoded; every match comes from the live index.
  ▼
  │  match_verify.py — download each social candidate's photo, re-encode,
  │            keep only matches showing the SAME face (cosine similarity).
  ▼
verified real social-media match (title, post URL, similarity score)
  │  blockchain.py / stellar.py — SHA-256 of the canonical record written
  │            as a Solana devnet Memo (primary) or Stellar testnet
  │            ManageData (fallback). Immutable once confirmed.
  ▼
out/record.json + out/tx.json + explorer URL
```

## Which blockchain

**Primary: Solana devnet** via your RPC (`SOLANA_RPC_URL`, e.g. Helius
`https://devnet.helius-rpc.com/?api-key=KEY`): auto-creates a keypair, funds
via faucet, writes a Memo (`MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`).
Verify at `https://explorer.solana.com/tx/<signature>?cluster=devnet`.

**Automatic fallback: Stellar testnet** — if the Solana faucet is
rate-limited, funds via the open Friendbot faucet and stores the record
SHA-256 (+ match URL) in `ManageData` ops.
Verify at `https://stellar.expert/explorer/testnet/tx/<hash>`.
`--chain solana|stellar|auto` selects explicitly (`auto` default).

## How to run

```bash
pip install -r requirements.txt  # pinned versions

# Full pipeline (face + live search + verify + chain):
python pipeline.py --image samples/elon_musk.jpg --out out

# Privacy mode (never publish local files; URL inputs only):
python pipeline.py --image https://example.com/photo.jpg --out out --no-upload

# Competition-strict: exit non-zero unless a FACE-VERIFIED social match exists:
python pipeline.py --image photo.jpg --out out --strict-social --threshold 0.45

# Face + search only (no chain write):
python pipeline.py --image photo.jpg --out out --skip-chain

# Verify a record against its on-chain data any time later:
python verify.py --tx <signature> --record out/record.json

# Accuracy benchmark over samples/groundtruth.json:
python bench.py

# Tests (10 offline + 3 network):
python -m pytest -m "not network" -q
python -m pytest -q  # includes live network tests

# One-command run (good for the screen recording):
bash run.sh samples/elon_musk.jpg
```

Secrets (env only — never committed, never logged):

| var | effect |
|---|---|
| `SERPAPI_API_KEY` | genuine Google Lens via SerpApi (`engine=google_lens`, `type=all`); else Yandex CBIR |
| `SOLANA_RPC_URL` | Solana RPC (default public devnet; Helius recommended) |
| `FBV_SKIP_MODEL_DOWNLOAD=1` | skip the ArcFace bundle; use offline fallback backend |

See `.env.example`. Artifacts in `out/`: `record.json` (canonical record +
`record_sha256` + verification), `matches.json` (ranked live matches),
`tx.json` (signature + explorer URL), `face_crop.jpg`, `id.json` / `stellar.json`
(auto-generated keypairs — 0600, git-ignored, keep secret).

Measured accuracy: see `ACCURACY.md`.

## Screen recording

To record the unedited end-to-end session:

```bash
bash demo_run.sh   # face → live search → verified match → chain → verify
```

`demo_run.sh` prints the `verify.py` command with the real signature at the
end — capture the whole terminal session in one take (OBS / gnome-screencast).
Older renders (`demo.mp4`, `demo.cast`) predate the verification step.

## Known limitations

- **Face recognition ≠ identity proof.** The embedding + similarity score prove
  the *same face* appears in both photos, not who the person legally is.
- **Reverse search depends on public indexes.** Lens / Yandex CBIR only find
  publicly indexed copies. Fresh or private photos may return zero social
  matches — `--strict-social` then exits 2 instead of recording a weak match.
- **Local files need a temporary public URL** (catbox.moe / tmpfiles.org) so
  the CBIR engine can fetch the bytes — unless `--no-upload` with a URL input.
  The bytes hashed in `record.json` are always the local original.
- **Solana devnet is a test network** (resettable, no mainnet value). Its
  faucet is rate-limited (Helius: 1 SOL/project/day); the pipeline fails over
  to Stellar testnet automatically.
- **Scraping fragility.** The keyless Yandex path parses pages that can change
  layout; SerpApi Lens is the stable path.
- **Privacy.** Only hashes + the match's public post URL go on-chain, never
  the photo or embedding — but reverse-searching someone else's photo without
  consent may violate platform ToS / local law. Use your own photos or
  public-figure samples (see `samples/`).
