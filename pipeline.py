#!/usr/bin/env python3
"""Face ID + Blockchain Verification — end-to-end pipeline.

  1. Detect + encode face from an input photo (face.py, ArcFace 512-d).
  2. Genuine live reverse-image search of the FULL image and the FACE CROP
     for a real matching social-media post (reverse_search.py).
  3. Face-verify each social candidate (match_verify.py): only a match whose
     photo contains the SAME face (cosine >= threshold) counts as verified.
  4. Write the verified match digest to Solana devnet (Helius RPC) as an
     immutable memo, Stellar testnet fallback (blockchain.py, stellar.py).

Usage:
  python pipeline.py --image samples/elon_musk.jpg --out out
  python pipeline.py --image https://.../photo.jpg --out out --no-upload
  python pipeline.py --image photo.jpg --out out --strict-social
  python verify.py --tx <signature> --record out/record.json

Secrets (never committed, never logged):
  SOLANA_RPC_URL  Solana RPC, e.g. https://devnet.helius-rpc.com/?api-key=KEY
  SERPAPI_API_KEY  SerpApi key for genuine Google Lens (else Yandex CBIR)
"""

import datetime
import hashlib
import ipaddress
import json
import os
import socket
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blockchain import send_memo, wait_confirmed  # noqa: E402
from cliutil import die, parser as make_parser  # noqa: E402
from face import detect_and_encode  # noqa: E402
from match_verify import DEFAULT_THRESHOLD, verify_match  # noqa: E402
from polygon import fetch_record as polygon_fetch  # noqa: E402
from polygon import send_record as polygon_send  # noqa: E402
from reverse_search import publish_image, search_url  # noqa: E402
from stellar import send_record as stellar_send  # noqa: E402

VERIFY_TOP_N = 8


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def guard_url(url):
    """SSRF guard: https/http only, host must resolve to a public IP."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"bad image URL: {url}")
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve image host: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError(f"refusing non-public image host "
                             f"{u.hostname} -> {ip}")
    return url


def keypair_safe(path, allow_risk=False):
    """Refuse keypair locations that git would commit (secret leak)."""
    parent = os.path.dirname(os.path.abspath(path)) or "."
    try:
        r = subprocess.run(["git", "check-ignore", "-q", path],
                           cwd=parent, capture_output=True, timeout=10)
    except Exception:  # noqa: BLE001 — no git available: allow, warn below
        return True
    if r.returncode == 0:
        return True  # git-ignored: safe
    # Check whether we're inside a repo at all.
    t = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       cwd=parent, capture_output=True, timeout=10)
    if t.returncode != 0:
        return True  # not a repo: nothing to leak into
    if allow_risk:
        print("       WARNING: keypair is NOT git-ignored; risk of commit.")
        return True
    die(f"refusing keypair at {path}: not git-ignored (secret leak risk). "
        "Put it under out/ (ignored) or pass --allow-keypair-risk.")


def merge_matches(*lists):
    seen, out = set(), []
    for lst, tag in lists:
        for m in lst:
            if m["page_url"] not in seen:
                seen.add(m["page_url"])
                m = dict(m)
                m["searched_as"] = tag
                out.append(m)
    return out


def main():
    ap = make_parser(
        "pipeline",
        "Face ID + blockchain verification: encode a face, find its real "
        "social-media post via live reverse-image search, face-verify it, "
        "and anchor the match on-chain.",
        "  pipeline --image samples/elon_musk.jpg --out out\n"
        "  pipeline --image photo.jpg --out out --strict-social --chain polygon\n"
        "  pipeline --image https://example.com/p.jpg --out out --no-upload\n"
        "  pipeline --image photo.jpg --out out --skip-chain")
    ap.add_argument("--image", required=True,
                    help="local photo path or public image URL")
    ap.add_argument("--out", default="out", help="output directory")
    ap.add_argument("--keypair", default=None,
                    help="solana keypair file (default: <out>/id.json)")
    ap.add_argument("--chain", default="auto",
                    choices=["auto", "solana", "stellar", "polygon"],
                    help="target chain (default: auto = solana devnet, "
                         "then stellar testnet, then polygon amoy)")
    ap.add_argument("--skip-chain", action="store_true",
                    help="run face + search only, skip blockchain write")
    ap.add_argument("--no-upload", action="store_true",
                    help="privacy mode: refuse to publish local files to a "
                         "public host; URL inputs only")
    ap.add_argument("--strict-social", action="store_true",
                    help="exit non-zero unless a FACE-VERIFIED social match "
                         "is found")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help="face-verification cosine threshold "
                         f"(default {DEFAULT_THRESHOLD})")
    ap.add_argument("--allow-keypair-risk", action="store_true",
                    help="allow a keypair path git would commit")
    args = ap.parse_args()

    is_url = args.image.startswith(("http://", "https://"))
    if args.no_upload and not is_url:
        die("--no-upload requires a public image URL input; "
            "local files would need publishing.")

    os.makedirs(args.out, exist_ok=True)
    keypair = args.keypair or os.path.join(args.out, "id.json")
    if not args.skip_chain and args.chain in ("auto", "solana"):
        keypair_safe(keypair, args.allow_keypair_risk)
    t0 = datetime.datetime.now(datetime.timezone.utc)
    wall = time.monotonic()

    print(f"Image : {args.image}")

    # Resolve image bytes.
    local = args.image
    if is_url:
        import urllib.request
        try:
            guard_url(args.image)
        except ValueError as e:
            die(str(e))
        local = os.path.join(args.out, "input_downloaded.jpg")
        urllib.request.urlretrieve(args.image, local)

    input_sha256 = sha256_file(local)

    # Step 1: face detect + encode.
    print("[1/4] Face ...", flush=True)
    face = detect_and_encode(local, out_dir=args.out)
    print(f"      {face['backend']}, {face['embedding_dim']}-d embedding")

    # Step 2: genuine reverse-image search (full image + face crop).
    print("[2/4] Search ...", flush=True)
    import reverse_search as rs
    if is_url:
        full_url, crop_src = args.image, os.path.join(args.out,
                                                      "face_crop.jpg")
    else:
        full_url = publish_image(local)
        crop_src = os.path.join(args.out, "face_crop.jpg")
    full_matches, provider, errors = search_url(full_url)
    crop_matches, crop_provider, crop_errors = [], provider, []
    if os.path.exists(crop_src):
        try:
            crop_url = full_url if is_url else publish_image(crop_src)
            crop_matches, crop_provider, crop_errors = search_url(crop_url)
            provider = provider or crop_provider
        except Exception as e:  # noqa: BLE001
            crop_errors.append(str(e))
    matches = merge_matches((full_matches, "full"), (crop_matches, "crop"))
    if not matches:
        die("reverse search returned no matches: " +
            " | ".join(errors + crop_errors))
    social = [m for m in matches if rs._is_social(m)]
    print(f"      {provider}: {len(matches)} matches, {len(social)} social posts")

    # Step 3: face-verify social candidates, rank verified first.
    print("[3/4] Verify ...", flush=True)
    for i, m in enumerate(social[:VERIFY_TOP_N], 1):
        v = verify_match(face["embedding"],
                         [m.get("image_url", ""), m.get("thumbnail_url", "")],
                         threshold=args.threshold)
        m["verification"] = v
        sim = v.get("similarity")
        sim_s = f"{sim:.4f}" if sim is not None else "n/a   "
        mark = "VERIFIED" if v["verified"] else "rejected"
        print(f"      #{i} [{mark}] {sim_s}  "
              f"{m['domain'][:32]:32} {m['page_url'][:60]}")
    verified = [m for m in social if m.get("verification", {}).get("verified")]
    verified.sort(key=lambda m: m["verification"]["similarity"],
                  reverse=True)
    unverified = [m for m in social
                  if not m.get("verification", {}).get("verified")]
    ranked = verified + unverified + [m for m in matches if m not in social]
    best = ranked[0]
    best_ver = best.get("verification", {})
    print(f"      {len(verified)}/{len(social)} same-face, "
          f"best: {best['domain']} (sim {best_ver.get('similarity')})")

    if args.strict_social and not best_ver.get("verified"):
        die("no face-verified social match (--strict-social)")
    with open(os.path.join(args.out, "matches.json"), "w") as f:
        json.dump(ranked[:50], f, indent=2, ensure_ascii=False)

    # Record assembly.
    record = {
        "app": "face-blockchain-verify",
        "created_utc": t0.isoformat(),
        "input": {"source": args.image, "sha256": input_sha256,
                  "public_url": full_url, "no_upload": args.no_upload},
        "face": {k: face[k] for k in ("backend", "bbox", "det_score",
                                      "embedding_dim", "embedding_sha256")},
        "reverse_search": {
            "provider": provider,
            "is_social_match": bool(social),
            "verified_match": bool(best_ver.get("verified")),
            "similarity": best_ver.get("similarity"),
            "threshold": args.threshold,
            "best_match": {k: best.get(k) for k in
                           ("title", "page_url", "domain", "image_url",
                            "thumbnail_url", "provider", "searched_as")},
            "match_verification": best_ver,
            "num_matches": len(matches),
            "num_social_matches": len(social),
            "num_verified": len(verified)},
    }
    record_json = json.dumps(record, sort_keys=True, ensure_ascii=False)
    record_sha256 = hashlib.sha256(record_json.encode()).hexdigest()
    record["record_sha256"] = record_sha256
    with open(os.path.join(args.out, "record.json"), "w") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

    # Step 4: blockchain write (Solana devnet primary, Stellar fallback).
    chain = None
    if not args.skip_chain:
        memo = (f"FACEVERIFY|{record_sha256}|{best['page_url']}|"
                f"{face['embedding_sha256'][:16]}")
        tried = []
        print("[4/4] Chain ...", flush=True)
        if args.chain in ("auto", "solana"):
            try:
                chain = send_memo(memo, keypair)
                chain["chain"] = "solana-devnet"
                wait_confirmed(chain["signature"])
            except Exception as e:  # noqa: BLE001
                tried.append(f"solana: {e}")
                chain = None
                if args.chain == "solana":
                    raise
        if chain is None and args.chain in ("auto", "polygon"):
            if os.environ.get("POLYGON_REGISTRY"):
                try:
                    chain = polygon_send(record_sha256, best["page_url"])
                    chain["chain"] = "polygon-amoy"
                    chain["memo"] = memo
                    if tried:
                        chain["fallback_from"] = tried
                except Exception as e:  # noqa: BLE001
                    tried.append(f"polygon: {e}")
                    chain = None
                    if args.chain == "polygon":
                        raise
            elif args.chain == "polygon":
                die("POLYGON_REGISTRY not set (deploy first: "
                    "python deploy_polygon.py)")
        if chain is None and args.chain in ("auto", "stellar"):
            chain = stellar_send(record_sha256, best["page_url"],
                                 os.path.join(args.out, "stellar.json"))
            chain["chain"] = "stellar-testnet"
            chain["memo"] = memo
            if tried:
                chain["fallback_from"] = tried
        print(f"      {chain['chain']}: {chain['signature'][:16]}... CONFIRMED")
        record["chain"] = chain
        with open(os.path.join(args.out, "record.json"), "w") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        with open(os.path.join(args.out, "tx.json"), "w") as f:
            json.dump(chain, f, indent=2)
    else:
        print("[4/4] Chain ... skipped (--skip-chain)")

    total = time.monotonic() - wall
    print()
    print(f"Best    : [{best['domain']}] sim {best_ver.get('similarity')} "
          f"{'(VERIFIED)' if best_ver.get('verified') else '(UNVERIFIED)'}")
    print(f"          {best['page_url']}")
    print(f"Record  : {record_sha256[:24]}... ({args.out}/record.json)")
    if chain:
        print(f"Tx      : {chain['signature']}")
        print(f"Explorer: {chain['explorer']}")
        print(f"Verify  : python verify.py --tx {chain['signature']} "
              f"--record {args.out}/record.json")
    print(f"Status  : {'MATCH on ' + chain['chain'] if chain else 'done (no chain write)'} "
          f"({total:.0f}s)")


if __name__ == "__main__":
    main()
