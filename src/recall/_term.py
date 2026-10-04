"""Tiny ANSI helper (honours NO_COLOR and non-TTY output)."""
from __future__ import annotations

import os
import sys

_CODES = {"dim": "2", "bold": "1", "red": "31", "green": "32", "yellow": "33",
          "blue": "34", "magenta": "35", "cyan": "36", "gray": "90"}


def enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def c(text: str, *styles: str) -> str:
    if not enabled():
        return text
    codes = ";".join(_CODES[s] for s in styles if s in _CODES)
    return f"\033[{codes}m{text}\033[0m" if codes else text
