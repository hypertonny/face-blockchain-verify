#!/usr/bin/env python3
"""fbv compile — compile FaceVerifyRegistry.sol to ABI + bytecode JSON."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import solcx  # noqa: E402
import ui  # noqa: E402
from cliutil import parser as make_parser  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv=None, prog=None):
    ap = make_parser(
        prog or "compile_contracts",
        "Compile FaceVerifyRegistry.sol with solc and write ABI + bytecode "
        "to compiled.json. Downloads the pinned compiler once.",
        "  compile_contracts\n"
        "  compile_contracts --solc 0.8.24 --out contracts/compiled.json")
    ap.add_argument("--solc", default="0.8.24", help="pinned solc version")
    ap.add_argument("--out", default=os.path.join(HERE, "compiled.json"),
                    help="output JSON path")
    args = ap.parse_args(argv)
    ui.step(1, 1, f"Compile FaceVerifyRegistry (solc {args.solc})")
    if args.solc not in [str(v) for v in solcx.get_installed_solc_versions()]:
        ui.info("downloading compiler (first run only)")
        solcx.install_solc(args.solc)
    solcx.set_solc_version(args.solc)
    out = solcx.compile_files(
        [os.path.join(HERE, "FaceVerifyRegistry.sol")],
        output_values=["abi", "bin"], optimize=True, optimize_runs=200)
    key = next(k for k in out if k.endswith(":FaceVerifyRegistry"))
    compiled = {"contract": "FaceVerifyRegistry", "solc": args.solc,
                "abi": out[key]["abi"], "bytecode": "0x" + out[key]["bin"]}
    with open(args.out, "w") as f:
        json.dump(compiled, f, indent=2)
    ui.ok(f"wrote {args.out} · {len(compiled['bytecode']) // 2} bytes")


if __name__ == "__main__":
    main()
