"""Shared CLI polish: version, examples epilogs, usage-error exits."""
import argparse

import ui

VERSION = "1.0.0"


def parser(prog, description, examples=""):
    """ArgumentParser with professional defaults + --version."""
    ap = argparse.ArgumentParser(
        prog=prog, description=description,
        epilog=f"examples:\n{examples}" if examples else None,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {VERSION}")
    return ap


def add_verbose(ap):
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show extra detail (hashes, timings, published URLs)")


def die(msg, hint=None, code=2):
    """Usage/validation errors exit 2 (argparse convention); runtime is 1."""
    ui.die(msg, hint=hint, code=code)
