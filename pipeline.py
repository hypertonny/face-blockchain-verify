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

import argparse
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


def rpc_host():
    """Solana RPC host with any API key redacted (never log secrets)."""
    raw = os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")
    u = urllib.parse.urlparse(raw)
    tag = " (default public endpoint)" if "api.devnet" in u.netloc else ""
    return f"{u.scheme}://{u.netloc}{u.path}{tag}"


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
    raise SystemExit(
        f"refusing keypair at {path}: not git-ignored (secret leak risk). "
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
    ap = argparse.ArgumentParser(description="Face ID + blockchain verification")
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
        raise SystemExit("--no-upload requires a public image URL input; "
                         "local files would need publishing.")

    os.makedirs(args.out, exist_ok=True)
    keypair = args.keypair or os.path.join(args.out, "id.json")
    if not args.skip_chain and args.chain in ("auto", "solana"):
        keypair_safe(keypair, args.allow_keypair_risk)
    t0 = datetime.datetime.now(datetime.timezone.utc)
    wall = time.monotonic()

    def tick(label):
        tick.last = getattr(tick, "last", wall)
        now = time.monotonic()
        print(f"{label}  [t+{now - wall:6.1f}s (+{now - tick.last:5.1f}s)]")
        tick.last = now

    print(f"       solana RPC: {rpc_host()}")
    print(f"       lens provider: "
          f"{'serpapi-google-lens' if os.environ.get('SERPAPI_API_KEY') else 'yandex-cbir'}")

    # Resolve image bytes.
    local = args.image
    if is_url:
        import urllib.request
        guard_url(args.image)
        local = os.path.join(args.out, "input_downloaded.jpg")
        urllib.request.urlretrieve(args.image, local)
        tick("[1/5] downloaded input")
        print(f"       -> {local}")
    else:
        tick("[1/5] input image")
        print(f"       {local}")

    input_sha256 = sha256_file(local)
    print(f"       sha256: {input_sha256}")

    # Step 1: face detect + encode.
    face = detect_and_encode(local, out_dir=args.out)
    tick("[2/5] face detected + encoded")
    print(f"       backend : {face['backend']}")
    print(f"       vector  : {face['embedding_dim']}-d, "
          f"sha256 {face['embedding_sha256'][:24]}...")
    print(f"       bbox    : {face['bbox']} (score {face['det_score']:.3f})")

    # Step 2: genuine reverse-image search (full image + face crop).
    import reverse_search as rs
    if is_url:
        full_url, crop_src = args.image, os.path.join(args.out,
                                                      "face_crop.jpg")
    else:
        full_url = publish_image(local)
        crop_src = os.path.join(args.out, "face_crop.jpg")
        print(f"       published input -> {full_url}")
    full_matches, provider, errors = search_url(full_url)
    print(f"       full-image search: {len(full_matches)} matches")
    crop_matches, crop_provider, crop_errors = [], provider, []
    if os.path.exists(crop_src):
        try:
            crop_url = full_url if is_url else publish_image(crop_src)
            crop_matches, crop_provider, crop_errors = search_url(crop_url)
            provider = provider or crop_provider
            print(f"       crop: matches={len(crop_matches)}")
        except Exception as e:  # noqa: BLE001
            crop_errors.append(str(e))
            print(f"       crop search failed: {e}")
    matches = merge_matches((full_matches, "full"), (crop_matches, "crop"))
    if not matches:
        raise SystemExit("reverse search returned no matches: " +
                         " | ".join(errors + crop_errors))
    social = [m for m in matches if rs._is_social(m)]
    tick("[3/5] live reverse-image search done "
         f"({provider}, {len(matches)} matches, {len(social)} social)")
    # Step 3: face-verify social candidates, rank verified first.
    print(f"       {'rank':4} {'verdict':7} {'sim':>7}  domain / post")
    print("       " + "-" * 88)
    for i, m in enumerate(social[:VERIFY_TOP_N], 1):
        v = verify_match(face["embedding"],
                         [m.get("image_url", ""), m.get("thumbnail_url", "")],
                         threshold=args.threshold)
        m["verification"] = v
        sim = v.get("similarity")
        sim_s = f"{sim:.4f}" if sim is not None else "n/a   "
        print(f"       #{i:<3} [{'VERIFIED' if v['verified'] else 'rejected'}] "
              f"{sim_s}  {m['domain'][:30]}")
        print(f"              {m['page_url'][:84]}")
    verified = [m for m in social if m.get("verification", {}).get("verified")]
    verified.sort(key=lambda m: m["verification"]["similarity"],
                  reverse=True)
    unverified = [m for m in social
                  if not m.get("verification", {}).get("verified")]
    ranked = verified + unverified + [m for m in matches if m not in social]
    best = ranked[0]
    best_ver = best.get("verification", {})
    tick(f"[4/5] verification done "
         f"({len(verified)}/{len(social)} verified same-face)")
    print(f"       best: [{best['domain']}] "
          f"verified={best_ver.get('verified')} "
          f"sim={best_ver.get('similarity')}")

    if args.strict_social and not best_ver.get("verified"):
        raise SystemExit("exit 2: no face-verified social match "
                         "(--strict-social)")
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
    print(f"       record sha256: {record_sha256}")

    # Step 4: blockchain write (Solana devnet primary, Stellar fallback).
    chain = None
    if not args.skip_chain:
        memo = (f"FACEVERIFY|{record_sha256}|{best['page_url']}|"
                f"{face['embedding_sha256'][:16]}")
        tried = []
        if args.chain in ("auto", "solana"):
            try:
                print("[5/5] writing memo to Solana devnet ...")
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
        if chain is None and args.chain in ("auto", "polygon"):
            if os.environ.get("POLYGON_REGISTRY"):
                try:
                    print("[5/5] anchoring record on Polygon Amoy ...")
                    chain = polygon_send(record_sha256, best["page_url"])
                    chain["chain"] = "polygon-amoy"
                    chain["memo"] = memo
                    print(f"       tx: {chain['signature']}")
                    print(f"       explorer: {chain['explorer']}")
                    print("       CONFIRMED on Polygon Amoy.")
                    if tried:
                        chain["fallback_from"] = tried
                except Exception as e:  # noqa: BLE001
                    tried.append(f"polygon: {e}")
                    chain = None
                    if args.chain == "polygon":
                        raise
            elif args.chain == "polygon":
                raise SystemExit("POLYGON_REGISTRY not set (deploy first: "
                                 "python deploy_polygon.py)")
        if chain is None and args.chain in ("auto", "stellar"):
            print("[5/5] writing record to Stellar testnet ...")
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
        print("[5/5] skipped (--skip-chain)")

    total = time.monotonic() - wall
    print()
    print("=" * 88)
    print(f" RESULT   {'VERIFIED SAME-FACE MATCH' if best_ver.get('verified') else 'UNVERIFIED match (see --strict-social)'}")
    print(f" POST     [{best['domain']}] {best['page_url'][:66]}")
    print(f" SIMILARITY {best_ver.get('similarity')} "
          f"(threshold {args.threshold}, backend {face['backend']})")
    if chain:
        print(f" CHAIN    {chain['chain']}")
        print(f" TX       {chain['signature']}")
        print(f" EXPLORER {chain['explorer']}")
        print(f" VERIFY   python verify.py --tx {chain['signature']} "
              f"--record {args.out}/record.json")
    print(f" ARTIFACTS {args.out}/record.json {args.out}/matches.json "
          f"{args.out}/tx.json {args.out}/face_crop.jpg")
    print(f" TIME     {total:.1f}s total")
    print("=" * 88)


if __name__ == "__main__":
    main()
