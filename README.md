# Face ID + Blockchain Verification

Pipeline that **detects + encodes a face** from a photo, finds a **real matching
social-media post via genuine live reverse-image search**, and writes that match
to a **blockchain as a tamper-evident, verifiable record**.

No website, no hosting — the pipeline itself is the deliverable.

## How it works

```
input photo
  │  face.py — detect largest face, compute embedding
  │            (InsightFace buffalo / ONNX ArcFace / OpenCV fallback)
  ▼
face embedding + bbox + sha256
  │  reverse_search.py — publish to temp public URL if local,
  │            then LIVE reverse-image query (SerpApi Google Lens if
  │            SERPAPI_API_KEY is set, else Yandex CBIR `cbir_page=sites`).
  │            Nothing is hardcoded; every match comes from the live index.
  │            Results are ranked to prefer real social-media posts.
  ▼
best real social-media match (title, post URL, domain, thumbnail)
  │  blockchain.py — SHA-256 of the canonical record is written as a
  │            Solana Memo instruction on **Solana devnet**.
  │            Immutable once confirmed; verifiable on the explorer.
  ▼
out/record.json + out/tx.json + explorer URL
```

## Which blockchain

**Primary: Solana devnet** — no API key or funded mainnet account needed: the
pipeline auto-creates a keypair, funds it via the devnet faucet, and writes a
Memo (`MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`).
Verify at `https://explorer.solana.com/tx/<signature>?cluster=devnet`.
Override the RPC with `SOLANA_RPC_URL` if needed.

**Automatic fallback: Stellar testnet** — if the Solana faucet is
rate-limited, the pipeline funds a fresh account via the open Friendbot faucet
and stores the record SHA-256 (+ match URL) in `ManageData` operations.
Verify at `https://stellar.expert/explorer/testnet/tx/<hash>`.
Select explicitly with `python pipeline.py --chain solana|stellar` (`auto` is
the default).

## How to run

```bash
pip install -r requirements.txt

# Full pipeline (face + live reverse search + devnet memo):
python pipeline.py --image samples/elon_musk.jpg --out out
# or any local photo / public URL:
python pipeline.py --image /path/to/photo.jpg --out out
python pipeline.py --image https://example.com/photo.jpg --out out

# Face + search only (no chain write):
python pipeline.py --image samples/elon_musk.jpg --out out --skip-chain

# Verify a record against its on-chain memo any time later:
python verify.py --tx <signature> --record out/record.json

# One-command run (good for the screen recording):
bash run.sh samples/elon_musk.jpg
```

Optional env vars:

| var | effect |
|---|---|
| `SERPAPI_API_KEY` | use genuine Google Lens via SerpApi instead of Yandex CBIR |
| `SOLANA_RPC_URL` | custom Solana RPC (default: devnet) |
| `FBV_SKIP_MODEL_DOWNLOAD=1` | skip the ~166 MB ArcFace bundle; use offline fallback backend |

Artifacts in `out/`: `record.json` (canonical record + `record_sha256`),
`matches.json` (all live matches), `tx.json` (signature + explorer URL),
`face_crop.jpg`, `id.json` (auto-generated devnet keypair — keep secret).

## Screen recording

`demo.mp4` is a full end-to-end run with no cuts: face detect + encode,
live reverse-image search (255 matches / 42 social), Solana attempt with
automatic Stellar fallback, on-chain confirmation, and `verify.py` printing
MATCH. `demo.cast` is the raw unedited terminal session (replay with
`asciinema play demo.cast`); `demo_run.sh` reproduces it, `render_cast.py`
rendered the video frame-by-frame from the recorded bytes.

To record your own unedited session:

```bash
bash run.sh samples/elon_musk.jpg
python verify.py --tx <signature-from-above> --record out/record.json
```

## Known limitations

- **Face recognition ≠ identity proof.** The embedding proves *a* face was
  encoded from the input pixels, not who the person legally is. The default
  offline backend (OpenCV + pixel embedding) is a detection + descriptor
  fallback, not a state-of-the-art recognizer; install `insightface` (or let
  the ArcFace bundle download) for real 512-d embeddings.
- **Reverse search depends on public indexes.** Yandex CBIR / SerpApi Lens only
  find publicly indexed copies. Private individuals, fresh photos, or heavily
  edited crops may return zero social matches — the pipeline then records the
  closest visual match and flags `is_social_match: false`.
- **Local files need a temporary public URL** (catbox.moe / tmpfiles.org) so
  the CBIR engine can fetch the bytes. The URL is transient; the bytes hashed
  in `record.json` are always the local original.
- **Solana devnet is a test network.** Memos there are tamper-evident and great
  for verification demos, but devnet history can be reset and carries no
  mainnet value. Airdrops are rate-limited; if the faucet is throttled the
  pipeline retries, then asks you to fund the printed address manually.
- **Scraping fragility.** The keyless Yandex path parses result pages that can
  change layout. If it breaks, set `SERPAPI_API_KEY` for the stable Lens API
  path — both are genuine reverse-image search, neither is hardcoded.
- **Privacy.** Only hashes + the match's public post URL go on-chain, never
  the photo or embedding — but reverse-searching someone else's photo without
  consent may violate platform ToS / local law. Use your own photos or
  public-figure samples (see `samples/`).
