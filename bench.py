#!/usr/bin/env python3
"""fbv bench — accuracy benchmark over samples/groundtruth.json."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui  # noqa: E402
from cliutil import add_verbose, parser as make_parser  # noqa: E402
from face import detect_and_encode  # noqa: E402
from match_verify import verify_match  # noqa: E402
import reverse_search as rs  # noqa: E402


def run_case(image, expected, threshold, top_n):
    face = detect_and_encode(image, out_dir=None)
    full_url = rs.publish_image(image)
    full, provider, _, identity = rs.search_url(full_url)
    x1, y1, x2, y2 = face["bbox"]
    import cv2
    img = cv2.imread(image)
    crop_path = "/tmp/opencode/bench_crop.jpg"
    cv2.imwrite(crop_path, img[y1:y2, x1:x2])
    crop, _, _, _ = rs.search_url(rs.publish_image(crop_path))
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
    verified = [m for m in social if m["verification"].get("verified")]
    verified.sort(key=lambda m: m["verification"]["similarity"], reverse=True)
    sims = [m["verification"]["similarity"] for m in social
            if m["verification"].get("similarity") is not None]
    top_by_similarity = (bool(verified) and bool(expected)
                         and verified[0]["page_url"].rstrip("/")
                         == expected.rstrip("/"))
    return {"image": image, "expected": expected, "provider": provider,
            "backend": face["backend"], "dim": face["embedding_dim"],
            "identity_person": identity.get("person", ""),
            "num_matches": len(merged), "num_social": len(social),
            "expected_rank": rank, "top1": rank == 1, "top5": rank is not None
            and rank <= 5, "top_by_similarity": top_by_similarity,
            "best_similarity": max(sims) if sims else None,
            "social": [{k: m.get(k) for k in
                        ("domain", "page_url", "image_url", "thumbnail_url",
                         "verification")} for m in social]}


def main(argv=None, prog=None):
    ap = make_parser(
        prog or "bench",
        "Benchmark accuracy: encode each ground-truth photo, live-search it, "
        "face-verify candidates, and measure expected-post recall/rank.",
        "  bench\n  bench --threshold 0.5 --top-n 12 --out bench_results.json")
    ap.add_argument("--groundtruth", default="samples/groundtruth.json",
                    help="JSON list of {image, expected_post_url}")
    ap.add_argument("--threshold", type=float, default=0.45,
                    help="same-face cosine threshold (default: 0.45)")
    ap.add_argument("--top-n", type=int, default=8,
                    help="social candidates to verify per case (default: 8)")
    ap.add_argument("--out", default="bench_results.json",
                    help="output JSON path")
    add_verbose(ap)
    args = ap.parse_args(argv)
    try:
        cases = json.load(open(args.groundtruth))
    except (OSError, ValueError) as e:
        ui.die(f"cannot read ground truth: {e}",
               hint="create samples/groundtruth.json or pass --groundtruth")
    if not cases:
        ui.die("ground truth set is empty",
               hint="add {image, expected_post_url} cases first")

    ui.step(1, 1, f"Benchmark — {len(cases)} case(s)")
    results = []
    for i, case in enumerate(cases, 1):
        image = case["image"]
        ui.info(f"{i}/{len(cases)} {image}")
        result = run_case(image, case.get("expected_post_url", ""),
                          args.threshold, args.top_n)
        results.append(result)
        mark = ui.c(ui.OK, "green", "bold") if result["top_by_similarity"] else ui.c(ui.FAIL, "red")
        ui.info(f"{mark} sim {result['best_similarity']} · "
                f"provider rank {result['expected_rank']}")
    n = len(results)
    summary = {
        "n": n,
        "top1": sum(r["top1"] for r in results) / n,
        "top5": sum(r["top5"] for r in results) / n,
        "top_by_similarity": sum(r["top_by_similarity"] for r in results) / n,
    }
    with open(args.out, "w") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2)
    print()
    ui.ok(f"{n} cases · top-1 similarity {summary['top_by_similarity']:.0%} "
          f"· provider top-5 {summary['top5']:.0%}")
    ui.info(f"results {args.out}")
    if args.verbose:
        ui.info(json.dumps(summary))


if __name__ == "__main__":
    main()
