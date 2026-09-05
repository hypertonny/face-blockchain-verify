#!/usr/bin/env python3
"""Face ID + Blockchain Verification — end-to-end pipeline.

  1. Detect + encode face from an input photo (face.py).
  2. Genuine live reverse-image search for a real matching social-media
     post (reverse_search.py) — no hardcoded results.
  3. Write the match digest to Solana devnet as an immutable memo
     (blockchain.py) — tamper-evident, publicly verifiable.

Usage:
  python pipeline.py --image samples/elon_musk.jpg --out out
  python pipeline.py --image https://.../photo.jpg --out out
  python verify.py --tx <signature> --record out/record.json
"""

import argparse
import datetime
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blockchain import fetch_memo, send_memo, wait_confirmed  # noqa: E402
from face import detect_and_encode  # noqa: E402
from reverse_search import reverse_search  # noqa: E402
from stellar import fetch_record as stellar_fetch  # noqa: E402
from stellar import send_record as stellar_send  # noqa: E402


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Face ID + blockchain verification")
    ap.add_argument("--image", required=True,
                    help="local photo path or public image URL")
    ap.add_argument("--out", default="out", help="output directory")
    ap.add_argument("--keypair", default=None,
                    help="solana keypair file (default: <out>/id.json)")
    ap.add_argument("--chain", default="auto",
                    choices=["auto", "solana", "stellar"],
                    help="target chain (default: auto = solana devnet, "
                         "stellar testnet fallback)")
    ap.add_argument("--skip-chain", action="store_true",
                    help="run face + search only, skip blockchain write")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    keypair = args.keypair or os.path.join(args.out, "id.json")
    t0 = datetime.datetime.now(datetime.timezone.utc)

    # Resolve image bytes.
    local = args.image
    if args.image.startswith(("http://", "https://")):
        import urllib.request
        local = os.path.join(args.out, "input_downloaded.jpg")
        urllib.request.urlretrieve(args.image, local)
        print(f"[1/4] downloaded input -> {local}")
    else:
        print(f"[1/4] input image: {local}")

    input_sha256 = sha256_file(local)
    print(f"       sha256: {input_sha256}")

    # Step 1: face detect + encode.
    print("[2/4] detecting + encoding face ...")
    face = detect_and_encode(local, out_dir=args.out)
    print(f"       backend={face['backend']} dim={face['embedding_dim']} "
          f"bbox={face['bbox']} emb_sha256={face['embedding_sha256'][:16]}...")

    # Step 2: genuine reverse-image search.
    print("[3/4] live reverse-image search (no hardcoded results) ...")
    search = reverse_search(args.image if args.image.startswith("http")
                            else local)
    best = search["best_match"]
    print(f"       provider={search['provider']} "
          f"matches={search['num_matches']} "
          f"social={search['num_social_matches']}")
    print(f"       best: [{best['domain']}] {best['title'][:90]}")
    print(f"             {best['page_url'][:120]}")

    # Record assembly.
    record = {
        "app": "face-blockchain-verify",
        "created_utc": t0.isoformat(),
        "input": {"source": args.image, "sha256": input_sha256,
                  "public_url": search["public_image_url"]},
        "face": {k: face[k] for k in ("backend", "bbox", "det_score",
                                      "embedding_dim", "embedding_sha256")},
        "reverse_search": {"provider": search["provider"],
                           "is_social_match": search["is_social_match"],
                           "best_match": best,
                           "num_matches": search["num_matches"],
                           "num_social_matches": search["num_social_matches"]},
    }
    record_json = json.dumps(record, sort_keys=True, ensure_ascii=False)
    record_sha256 = hashlib.sha256(record_json.encode()).hexdigest()
    record["record_sha256"] = record_sha256
    with open(os.path.join(args.out, "record.json"), "w") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    with open(os.path.join(args.out, "matches.json"), "w") as f:
        json.dump(search["matches"], f, indent=2, ensure_ascii=False)
    print(f"       record sha256: {record_sha256}")

    # Step 3: blockchain write (Solana devnet primary, Stellar fallback).
    chain = None
    if not args.skip_chain:
        memo = (f"FACEVERIFY|{record_sha256}|{best['page_url']}|"
                f"{face['embedding_sha256'][:16]}")
        tried = []
        if args.chain in ("auto", "solana"):
            try:
                print("[4/4] writing memo to Solana devnet ...")
                chain = send_memo(memo, keypair)
                chain["chain"] = "solana-devnet"
                print(f"       tx: {chain['signature']}")
                print(f"       explorer: {chain['explorer']}")
                print("       waiting for confirmation ...")
                wait_confirmed(chain["signature"])
                print("       CONFIRMED on Solana devnet.")
            except Exception as e:  # noqa: BLE001
                tried.append(f"solana: {e}")
                chain = None
                if args.chain == "solana":
                    raise
                print(f"       solana unavailable ({e}); "
                      "falling back to Stellar testnet ...")
        if chain is None:
            print("[4/4] writing record to Stellar testnet ...")
            chain = stellar_send(record_sha256, best["page_url"],
                                 os.path.join(args.out, "stellar.json"))
            chain["chain"] = "stellar-testnet"
            chain["memo"] = memo
            print(f"       tx: {chain['signature']}")
            print(f"       explorer: {chain['explorer']}")
            print("       CONFIRMED on Stellar testnet.")
            if tried:
                chain["fallback_from"] = tried
        record["chain"] = chain
        with open(os.path.join(args.out, "record.json"), "w") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        with open(os.path.join(args.out, "tx.json"), "w") as f:
            json.dump(chain, f, indent=2)
    else:
        print("[4/4] skipped (--skip-chain)")

    print("\nDONE. Artifacts in", args.out)
    if chain:
        print("Verify any time with:")
        print(f"  python verify.py --tx {chain['signature']} "
              f"--record {args.out}/record.json")


if __name__ == "__main__":
    main()
