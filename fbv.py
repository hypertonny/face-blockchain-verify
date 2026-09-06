#!/usr/bin/env python3
"""fbv — Face ID + Blockchain Verification toolkit.

  fbv run      detect face, find + verify social match, anchor on-chain
  fbv verify   re-verify a record against its on-chain data
  fbv bench    accuracy benchmark over samples/groundtruth.json
  fbv deploy   deploy FaceVerifyRegistry to Polygon Amoy (you sign locally)
  fbv compile  compile the Solidity registry contract

Each subcommand also works standalone: python pipeline.py / verify.py /
bench.py / deploy_polygon.py. Run `fbv <cmd> --help` for options.
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui  # noqa: E402
from cliutil import VERSION  # noqa: E402

COMMANDS = [
    ("run", "face -> live reverse search -> face-verify -> on-chain record"),
    ("verify", "re-verify a record against its on-chain data"),
    ("bench", "accuracy benchmark over samples/groundtruth.json"),
    ("deploy", "deploy FaceVerifyRegistry to Polygon Amoy"),
    ("compile", "compile the Solidity registry contract"),
]

_MODULES = {"run": "pipeline", "verify": "verify", "bench": "bench",
            "deploy": "deploy_polygon", "compile": "compile_contracts"}


def usage():
    lines = [f"fbv {VERSION} \u2014 Face ID + Blockchain Verification", "",
             "usage: fbv <command> [options]", "", "commands:"]
    w = max(len(c) for c, _ in COMMANDS)
    lines += [f"  {c.ljust(w)}  {d}" for c, d in COMMANDS]
    lines += ["", "options:",
              "  -h, --help     show this help",
              "  -V, --version  show version", "",
              f"Run {ui.c('fbv <command> --help', 'bold')} for command options."]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    if argv[0] in ("-V", "--version"):
        print(f"fbv {VERSION}")
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd not in _MODULES:
        ui.die(f"unknown command '{cmd}'",
               hint="run 'fbv --help' to list commands")
    if cmd == "compile":
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "contracts"))
    mod = importlib.import_module(_MODULES[cmd])
    return mod.main(rest, prog=f"fbv {cmd}") or 0


if __name__ == "__main__":
    sys.exit(main())
