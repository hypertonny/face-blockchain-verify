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

## Ground-truth benchmark — user samples (2026-09-06)

SerpApi Google Lens (`type=all`), dual search (full + crop), InsightFace
512-d, threshold 0.45. `verified` = same face confirmed by cosine similarity.

| image | matches / social / verified | best verified post | sim |
|---|---|---|---|
| image-1 (apparent Mr. Faisu) | 116 / 8 / 5 | pinterest.com/pin/848928598502276539 (also IG `_mr_faisu_07_tm`, TikTok `@mr_faisu_07` video, FB photos all verified) | 0.6756 |
| image-2 | 119 / 8 / 6+ | instagram.com/reel/Db7KsNXpo-9 (also YT short, reddit, FB verified) | 0.8904 |
| image-3 | 116 / 8 / 5 | reddit r/InstaCelebsGossip (also FB 0.9564, IG 0.9421, X 0.9391) | 0.9692 |
| image-4 (apparent Tom Holland) | 111 / 8 / 6+ | instagram.com/p/DbUcFQajOhf (also X, threads, FB verified) | 0.9101 |
| image-5 (apparent Akshay Kumar) | 119 / 8 / 1 | facebook.com/p/Iam-joy-61589795287166 — modest score, needs human confirmation | 0.5568 |

Correctly rejected lookalikes: LinkedIn post 0.1399, Jim Caviezel board
0.0051, unrelated IG/FB posts ~0.0 (below threshold). Full per-candidate
data: run `python bench.py` (needs the local-only sample photos).

`samples/groundtruth.json` template is in the repo; fill
`expected_post_url` per image to lock top-1/top-5 regression scores.
