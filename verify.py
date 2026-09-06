#!/usr/bin/env python3
"""fbv verify — re-verify a pipeline record against its on-chain data."""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui  # noqa: E402
from blockchain import fetch_memo  # noqa: E402
from cliutil import parser as make_parser  # noqa: E402
from polygon import fetch_record as polygon_fetch  # noqa: E402
from stellar import fetch_record as stellar_fetch  # noqa: E402


def main(argv=None, prog=None):
    ap = make_parser(
        prog or "verify",
        "Re-verify a pipeline record: recompute its canonical SHA-256 and "
        "compare with the on-chain memo / manage-data / contract anchor. "
        "Exit 0 on MATCH, 1 on MISMATCH.",
        "  verify --tx <signature> --record out/record.json")
    ap.add_argument("--tx", required=True, help="on-chain transaction hash")
    ap.add_argument("--record", required=True, help="record.json to check")
    args = ap.parse_args(argv)

    try:
        record = json.load(open(args.record))
    except (OSError, ValueError) as e:
        ui.die(f"cannot read record: {e}",
               hint="run 'fbv run' first to produce out/record.json")
    canonical = {k: v for k, v in record.items()
                 if k not in ("record_sha256", "chain")}
    expect = hashlib.sha256(
        json.dumps(canonical, sort_keys=True,
                   ensure_ascii=False).encode()).hexdigest()

    chain = (record.get("chain") or {}).get("chain", "solana-devnet")
    ui.step(1, 2, "Recompute record digest")
    ui.info(f"local      {record.get('record_sha256')}")
    ui.info(f"recomputed {expect}")
    ui.step(2, 2, f"Fetch on-chain data ({chain})")
    try:
        if "polygon" in chain:
            got = polygon_fetch(args.tx)
            ui.info(f"contract   {got['contract']}")
            ui.info(f"submitter  {got['submitter']}")
            ui.info(f"match_url  {got['match_url']}")
            ok = (got["record_hash"] == record.get("record_sha256") == expect
                  and got["stored"]["exists"])
        elif "stellar" in chain:
            got = stellar_fetch(args.tx)["manage_data"]
            ui.info(f"manage_data {got}")
            import base64
            raw = got.get("fbv-record", "")
            try:
                onchain = base64.b64decode(raw).decode()
            except Exception:  # noqa: BLE001
                onchain = raw
            ok = (onchain == record.get("record_sha256") == expect)
        else:
            memo = fetch_memo(args.tx)
            ui.info(f"memo      {memo}")
            parts = memo.split("|")
            ok = (len(parts) >= 2 and parts[0] == "FACEVERIFY"
                  and parts[1] == record.get("record_sha256") == expect)
    except RuntimeError as e:
        ui.die(str(e), hint="check the tx hash, network, and that "
                            "POLYGON_REGISTRY is set for polygon records")
    if ok:
        ui.ok(f"MATCH — record is tamper-evident on {chain}")
    else:
        ui.fail("MISMATCH — record differs from on-chain digest")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
