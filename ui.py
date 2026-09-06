"""Terminal UI: colors (TTY-aware, NO_COLOR-respecting) + symbols."""
import os
import sys

_CODES = {"red": "31", "green": "32", "yellow": "33", "cyan": "36",
          "gray": "90", "bold": "1"}

OK, FAIL, WARN, ARROW = "\u2713", "\u2717", "\u26a0", "\u2192"


def supports_color():
    return (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
            and os.environ.get("NO_COLOR") is None
            and os.environ.get("TERM") != "dumb")


def c(text, *styles):
    if not supports_color() or not styles:
        return text
    seq = ";".join(_CODES[s] for s in styles)
    return f"\033[{seq}m{text}{_RESET}"


_RESET = "\033[0m"


def bold(text):
    return c(text, "bold")


def dim(text):
    return c(text, "gray")


def step(n, total, label):
    print(f"{c(f'[{n}/{total}]', 'cyan', 'bold')} {label}", flush=True)


def info(msg):
    print(f"   {msg}")


def ok(msg):
    print(f"  {c(OK, 'green', 'bold')} {msg}")


def fail(msg):
    print(f"  {c(FAIL, 'red', 'bold')} {msg}")


def warn(msg):
    print(f"  {c(WARN, 'yellow', 'bold')} {msg}")


def die(msg, hint=None, code=2):
    """Usage/validation error with optional actionable hint."""
    print(f"{c(FAIL + ' error:', 'red', 'bold')} {msg}", file=sys.stderr)
    if hint:
        print(f"  {c('hint:', 'yellow')} {hint}", file=sys.stderr)
    raise SystemExit(code)
