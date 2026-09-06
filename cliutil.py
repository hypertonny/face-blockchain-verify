"""Shared CLI polish: version, examples epilogs, usage-error exits."""
import argparse
import sys

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


def die(msg, code=2):
    """Usage/validation errors exit 2 (argparse convention); runtime is 1."""
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)
