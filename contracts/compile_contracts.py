#!/usr/bin/env python3
"""Compile contracts/*.sol -> contracts/compiled.json (ABI + bytecode).

Needs the solc 0.8.24 binary (py-solc-x downloads it once):
  python -c "import solcx; solcx.install_solc('0.8.24')"
No keys, no network (after solc is cached). Safe to commit the output.
"""
import json
import os

import solcx

HERE = os.path.dirname(os.path.abspath(__file__))
SOLC = "0.8.24"


def main():
    if SOLC not in [str(v) for v in solcx.get_installed_solc_versions()]:
        solcx.install_solc(SOLC)
    solcx.set_solc_version(SOLC)
    out = solcx.compile_files(
        [os.path.join(HERE, "FaceVerifyRegistry.sol")],
        output_values=["abi", "bin"],
        optimize=True, optimize_runs=200)
    key = next(k for k in out if k.endswith(":FaceVerifyRegistry"))
    compiled = {"contract": "FaceVerifyRegistry", "solc": SOLC,
                "abi": out[key]["abi"], "bytecode": "0x" + out[key]["bin"]}
    dest = os.path.join(HERE, "compiled.json")
    with open(dest, "w") as f:
        json.dump(compiled, f, indent=2)
    print(f"wrote {dest} "
          f"({len(compiled['bytecode']) // 2} bytecode bytes)")


if __name__ == "__main__":
    main()
