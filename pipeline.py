#!/usr/bin/env python3
"""fbv run — Face ID + Blockchain Verification pipeline.

  1. Detect + encode face from an input photo (face.py, ArcFace 512-d).
  2. Genuine live reverse-image search of the FULL image and the FACE CROP
     for a real matching social-media post (reverse_search.py).
  3. Face-verify each social candidate (match_verify.py): only a match whose
     photo contains the SAME face (cosine >= threshold) counts as verified.
  4. Write the verified match digest to Solana devnet (primary), Polygon
     Amoy registry, or Stellar testnet — tamper-evident, publicly verifiable.

Usage:
  fbv run --image samples/elon_musk.jpg --out out
  fbv run --image photo.jpg --out out --strict-social --chain polygon
  fbv run --image https://example.com/p.jpg --out out --no-upload -v
  fbv verify --tx <signature> --record out/record.json

Secrets (env only — never committed, never logged):
  SOLANA_RPC_URL   Solana RPC, e.g. https://devnet.helius-rpc.com/?api-key=KEY
  SERPAPI_API_KEY  SerpApi key for genuine Google Lens (else Yandex CBIR)
  POLYGON_REGISTRY / POLYGON_PRIVATE_KEY  Polygon Amoy anchor writes
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
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui  # noqa: E402
from blockchain import send_memo, wait_confirmed  # noqa: E402
from cliutil import add_verbose, parser as make_parser  # noqa: E402
from face import detect_and_encode  # noqa: E402
from match_verify import DEFAULT_THRESHOLD, verify_match  # noqa: E402
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
    except Exception:  # noqa: BLE001 — no git available: allow
        return True
    if r.returncode == 0:
        return True  # git-ignored: safe
    t = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       cwd=parent, capture_output=True, timeout=10)
    if t.returncode != 0:
        return True  # not a repo: nothing to leak into
    if allow_risk:
        ui.warn("keypair is NOT git-ignored; risk of commit.")
        return True
    ui.die(f"refusing keypair at {path}: not git-ignored (secret leak risk)",
           hint="put it under out/ (ignored) or pass --allow-keypair-risk")


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


def main(argv=None, prog=None):
    ap = make_parser(
        prog or "pipeline",
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
                         "then polygon amoy if configured, then stellar)")
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
    add_verbose(ap)
    args = ap.parse_args(argv)

    is_url = args.image.startswith(("http://", "https://"))
    if args.no_upload and not is_url:
        ui.die("--no-upload requires a public image URL input",
               hint="local files must be published for reverse search; "
                    "drop --no-upload or pass an image URL")
    if is_url:
        try:
            guard_url(args.image)
        except ValueError as e:
            ui.die(str(e), hint="only public http(s) image URLs are allowed")

    os.makedirs(args.out, exist_ok=True)
    keypair = args.keypair or os.path.join(args.out, "id.json")
    if not args.skip_chain and args.chain in ("auto", "solana"):
        keypair_safe(keypair, args.allow_keypair_risk)
    t0 = datetime.datetime.now(datetime.timezone.utc)
    wall = time.monotonic()
    laps, last = [], [wall]

    def lap():
        now = time.monotonic()
        laps.append(now - last[0])
        last[0] = now

    print(f"{ui.bold('fbv run')} {ui.c(args.image, 'bold')} "
          f"{ui.ARROW} {args.out}")

    # Resolve image bytes.
    local = args.image
    if is_url:
        import urllib.request
        local = os.path.join(args.out, "input_downloaded.jpg")
        urllib.request.urlretrieve(args.image, local)
    input_sha256 = sha256_file(local)
    if args.verbose:
        ui.info(f"input sha256 {input_sha256}")

    # Step 1: face detect + encode.
    ui.step(1, 4, "Face — detect + encode")
    face = detect_and_encode(local, out_dir=args.out)
    ui.info(f"{face['backend']} · {face['embedding_dim']}-d · "
            f"bbox {face['bbox']} · score {face['det_score']:.3f}")
    if args.verbose:
        ui.info(f"embedding sha256 {face['embedding_sha256']}")
    lap()

    # Step 2: genuine reverse-image search (full image + face crop, parallel).
    ui.step(2, 4, "Search — live reverse-image search (full + face crop)")
    import reverse_search as rs
    crop_src = os.path.join(args.out, "face_crop.jpg")
    if is_url:
        full_url = crop_url = args.image
    else:
        full_url = publish_image(local)
        crop_url = publish_image(crop_src) if os.path.exists(crop_src) else None
    if args.verbose:
        ui.info(f"published {full_url}")
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_full = ex.submit(search_url, full_url)
        fut_crop = (ex.submit(search_url, crop_url)
                    if crop_url and crop_url != full_url else None)
        full_matches, provider, errors = fut_full.result()
        crop_matches, crop_errors = [], []
        if fut_crop:
            crop_matches, _, crop_errors = fut_crop.result()
    matches = merge_matches((full_matches, "full"), (crop_matches, "crop"))
    if not matches:
        ui.die("reverse search returned no matches",
               hint=" | ".join(errors + crop_errors)
               or "try another photo, or set SERPAPI_API_KEY")
    social = [m for m in matches if rs._is_social(m)]
    ui.info(f"{provider} · {len(matches)} matches · {len(social)} social")
    lap()

    # Step 3: face-verify social candidates (parallel downloads), rank.
    ui.step(3, 4, f"Verify — face-check top {min(VERIFY_TOP_N, len(social))} "
                  "social candidates")
    cands = social[:VERIFY_TOP_N]

    def _v(m):
        m["verification"] = verify_match(
            face["embedding"],
            [m.get("image_url", ""), m.get("thumbnail_url", "")],
            threshold=args.threshold)

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(_v, cands))
    for m in cands:
        v = m["verification"]
        sim = v.get("similarity")
        sim_s = f"{sim:.4f}" if sim is not None else "  n/a"
        mark = (ui.c(ui.OK, "green", "bold") if v["verified"]
                else ui.c(ui.FAIL, "red"))
        print(f"   {mark} {sim_s}  {m['domain'][:30]:30} "
              f"{m['page_url'][:60]}")
    verified = [m for m in social if m.get("verification", {}).get("verified")]
    verified.sort(key=lambda m: m["verification"]["similarity"],
                  reverse=True)
    unverified = [m for m in social
                  if not m.get("verification", {}).get("verified")]
    ranked = verified + unverified + [m for m in matches if m not in social]
    best = ranked[0]
    best_ver = best.get("verification", {})
    ui.info(f"{len(verified)}/{len(social)} same-face verified")
    lap()

    if args.strict_social and not best_ver.get("verified"):
        ui.die("no face-verified social match (--strict-social)",
               hint=f"lower --threshold (now {args.threshold}) or drop "
                    "--strict-social")
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

    # Step 4: blockchain write.
    chain = None
    if not args.skip_chain:
        ui.step(4, 4, f"Chain — anchor record ({args.chain})")
        memo = (f"FACEVERIFY|{record_sha256}|{best['page_url']}|"
                f"{face['embedding_sha256'][:16]}")
        tried = []
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
                ui.warn(f"solana unavailable: {e}")
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
                    ui.warn(f"polygon unavailable: {e}")
            elif args.chain == "polygon":
                ui.die("POLYGON_REGISTRY not set",
                       hint="deploy first: fbv deploy (then export "
                            "POLYGON_REGISTRY=0x...)")
        if chain is None and args.chain in ("auto", "stellar"):
            chain = stellar_send(record_sha256, best["page_url"],
                                 os.path.join(args.out, "stellar.json"))
            chain["chain"] = "stellar-testnet"
            chain["memo"] = memo
            if tried:
                chain["fallback_from"] = tried
        ui.ok(f"{chain['chain']} · CONFIRMED")
        record["chain"] = chain
        with open(os.path.join(args.out, "record.json"), "w") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        with open(os.path.join(args.out, "tx.json"), "w") as f:
            json.dump(chain, f, indent=2)
        lap()
    else:
        ui.step(4, 4, "Chain — skipped (--skip-chain)")

    # Summary.
    total = time.monotonic() - wall
    print()
    if best_ver.get("verified"):
        print(f"{ui.c(ui.OK + ' VERIFIED SAME-FACE MATCH', 'green', 'bold')}")
    else:
        print(f"{ui.c(ui.WARN + ' UNVERIFIED MATCH', 'yellow', 'bold')} "
              f"{ui.dim('(use --strict-social to require verification)')}")
    ui.info(f"post     {best['page_url']}")
    ui.info(f"sim      {best_ver.get('similarity')} "
            f"(threshold {args.threshold})")
    if chain:
        ui.info(f"chain    {chain['chain']}")
        ui.info(f"tx       {chain['signature']}")
        ui.info(f"explorer {chain['explorer']}")
        ui.info(f"verify   fbv verify --tx {chain['signature']} "
                f"--record {args.out}/record.json")
    if args.verbose:
        names = ["face", "search", "verify", "chain"]
        ui.info("timings " + " · ".join(
            f"{n} {d:.1f}s" for n, d in zip(names, laps)))
    ui.info(f"time     {total:.0f}s")


if __name__ == "__main__":
    main()
