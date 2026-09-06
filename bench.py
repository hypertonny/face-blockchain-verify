#!/usr/bin/env python3
"""Accuracy benchmark over samples/groundtruth.json.

groundtruth.json: [{"image": "samples/image-1.png",
                    "expected_post_url": "https://x.com/.../status/..."}]

For each case: encode face, reverse-search (full + crop), face-verify top
social candidates, report the rank of the expected URL and best similarity.
Writes bench_results.json. Consumes SerpApi quota when SERPAPI_API_KEY is
set (2 searches/image); use --provider yandex to stay free.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cliutil import parser as make_parser  # noqa: E402
from face import detect_and_encode  # noqa: E402
from match_verify import verify_match  # noqa: E402
import reverse_search as rs  # noqa: E402


def run_case(image, expected, threshold, top_n):
    face = detect_and_encode(image, out_dir=None)
    full_url = rs.publish_image(image)
    full, provider, _ = rs.search_url(full_url)
    x1, y1, x2, y2 = face["bbox"]
    import cv2
    img = cv2.imread(image)
    crop_path = "/tmp/opencode/bench_crop.jpg"
    cv2.imwrite(crop_path, img[y1:y2, x1:x2])
    crop, _, _ = rs.search_url(rs.publish_image(crop_path))
    seen, merged = set(), []
    for m in full + crop:
        if m["page_url"] not in seen:
            seen.add(m["page_url"])
            merged.append(m)
    social = [m for m in merged if rs._is_social(m)][:top_n]
    for m in social:
        m["verification"] = verify_match(
            face["embedding"],
            [m.get("image_url", ""), m.get("thumbnail_url", "")],
            threshold=threshold)
    rank = None
    if expected:
        rank = next((i + 1 for i, m in enumerate(merged)
                     if expected.rstrip("/") in m["page_url"].rstrip("/")),
                    None)
    sims = [m["verification"]["similarity"] for m in social
            if m["verification"].get("similarity") is not None]
    return {"image": image, "expected": expected, "provider": provider,
            "backend": face["backend"], "dim": face["embedding_dim"],
            "num_matches": len(merged), "num_social": len(social),
            "expected_rank": rank, "top1": rank == 1, "top5": rank is not None
            and rank <= 5, "best_similarity": max(sims) if sims else None,
            "social": [{k: m.get(k) for k in
                        ("domain", "page_url", "image_url", "thumbnail_url",
                         "verification")} for m in social]}


def main():
    ap = make_parser(
        "bench",
        "Accuracy benchmark over samples/groundtruth.json: encode each "
        "photo, reverse-search it, face-verify candidates, and report the "
        "rank of the expected URL plus best similarity.",
        "  bench\n  bench --threshold 0.5 --top-n 12 --out bench_results.json")
    ap.add_argument("--groundtruth", default="samples/groundtruth.json",
                    help="JSON list of {image, expected_post_url}")
    ap.add_argument("--threshold", type=float, default=0.45)
    ap.add_argument("--top-n", type=int, default=8)
    ap.add_argument("--out", default="bench_results.json")
    args = ap.parse_args()
    cases = json.load(open(args.groundtruth))
    results = [run_case(c["image"], c["expected_post_url"],
                        args.threshold, args.top_n) for c in cases]
    n = len(results)
    summary = {"n": n,
               "top1": sum(r["top1"] for r in results) / n if n else 0,
               "top5": sum(r["top5"] for r in results) / n if n else 0}
    json.dump({"summary": summary, "results": results},
              open(args.out, "w"), indent=2)
    print(json.dumps(summary, indent=2))
    for r in results:
        print(f"{r['image']}: rank={r['expected_rank']} "
              f"best_sim={r['best_similarity']}")


if __name__ == "__main__":
    main()
