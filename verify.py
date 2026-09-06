#!/usr/bin/env python3
"""Verify a pipeline record against its on-chain data (all chains)."""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blockchain import fetch_memo  # noqa: E402
from cliutil import parser as make_parser  # noqa: E402
from polygon import fetch_record as polygon_fetch  # noqa: E402
from stellar import fetch_record as stellar_fetch  # noqa: E402


def main():
    ap = make_parser(
        "verify",
        "Re-verify a pipeline record: recompute its canonical SHA-256 and "
        "compare with the on-chain memo / manage-data / contract anchor. "
        "Exit 0 on MATCH, 1 on MISMATCH.",
        "  verify --tx <signature> --record out/record.json")
    ap.add_argument("--tx", required=True, help="on-chain transaction hash")
    ap.add_argument("--record", required=True, help="record.json to check")
    args = ap.parse_args()

    try:
        record = json.load(open(args.record))
    except (OSError, ValueError) as e:
        print(f"error: cannot read record: {e}", file=sys.stderr)
        raise SystemExit(2)
    canonical = {k: v for k, v in record.items()
                 if k not in ("record_sha256", "chain")}
    expect = hashlib.sha256(
        json.dumps(canonical, sort_keys=True,
                   ensure_ascii=False).encode()).hexdigest()

    chain = (record.get("chain") or {}).get("chain", "solana-devnet")
    if "polygon" in chain:
        got = polygon_fetch(args.tx)
        print("on-chain anchor:", {k: got[k] for k in
                                   ("contract", "record_hash", "submitter",
                                    "match_url", "timestamp")})
        ok = (got["record_hash"] == record.get("record_sha256") == expect
              and got["stored"]["exists"])
    elif "stellar" in chain:
        got = stellar_fetch(args.tx)["manage_data"]
        print("on-chain manage_data:", got)
        import base64
        raw = got.get("fbv-record", "")
        try:
            onchain = base64.b64decode(raw).decode()
        except Exception:  # noqa: BLE001
            onchain = raw
        ok = (onchain == record.get("record_sha256") == expect)
    else:
        memo = fetch_memo(args.tx)
        print("on-chain memo:", memo)
        parts = memo.split("|")
        ok = (len(parts) >= 2 and parts[0] == "FACEVERIFY"
              and parts[1] == record.get("record_sha256") == expect)
    print("local  record_sha256:", record.get("record_sha256"))
    print("recomputed sha256   :", expect)
    print("MATCH — record is tamper-evident on " + chain
          if ok else "MISMATCH — record differs from on-chain digest")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
