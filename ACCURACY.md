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

## Ground-truth benchmark — user samples (2026-09-06, locked)

SerpApi Google Lens (`type=all`), dual search (full + crop), InsightFace
512-d, threshold 0.45. Expected URLs confirmed correct by the user.
Recall (expected post found anywhere in merged candidates): **5/5**.
Top-1 by the pipeline's own similarity ranking: **5/5**.
(Raw provider-order top-5 is 2/5 — provider order is noisy, which is exactly
why the pipeline re-ranks by face similarity instead of trusting it.)

| image | expected post (confirmed) | sim | provider-order rank |
|---|---|---|---|
| image-1 | pinterest.com/pin/848928598502276539 | 0.6756 | 7 |
| image-2 | instagram.com/reel/Db7KsNXpo-9 | 0.8904 | 5 |
| image-3 | reddit r/InstaCelebsGossip | 0.9692 | 4 |
| image-4 | x.com/i/status/2095857089734443264 | 0.9646 | 17 |
| image-5 | facebook.com/p/Iam-joy-61589795287166 | 0.5568 | 10 |

`python bench.py` reproduces this from `samples/groundtruth.json`
(sample photos stay local-only and are git-ignored).
