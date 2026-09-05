# Accuracy report

Measured with the pipeline's face-verification step
(cosine similarity on the same encoder, threshold 0.45).

## Reference run — `samples/elon_musk.jpg` (2026-09-05)

| stage | result |
|---|---|
| Face backend | `insightface-buffalo_s`, 512-d ArcFace, det. score 0.832 |
| Reverse provider | SerpApi Google Lens (`type=all`) |
| Matches found | 112 total / 5 social / **3 face-verified** |
| Best match | `x.com/Jeetuburdak/status/2018172100721480144` |
| Best similarity | **0.9687** (verified=True) |
| Chain record | Stellar testnet `95de4c44…0df2e`, `verify.py` → MATCH |

Earlier keyless run (Yandex CBIR): 255 matches / 42 social (unverified
ranking). SerpApi returns fewer, higher-precision candidates; the
verification step then selects by face similarity rather than index order.

## Ground-truth benchmark — pending user samples

`samples/groundtruth.json` format:

```json
[{"image": "samples/image-1.png",
  "expected_post_url": "https://x.com/.../status/..."}]
```

Run `python bench.py` → `bench_results.json` with top-1/top-5 hit-rate and
best verified similarity per case. Fill this table once `image-1..5.png`
are placed in `samples/`.
