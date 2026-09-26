"""Minimal, dependency-free ANSI color for the CLI.

Color is opt-out and safe by default: it is emitted only to a real terminal,
never when output is piped or redirected, and never when ``NO_COLOR`` is set —
so evidence logs, pipes, and CI output stay byte-clean. This matters here
because the same commands that print for a human (``runs``, ``show``) are also
scraped by scripts; coloring must never corrupt that.
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

_CODES = {
    "reset": "0",
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "cyan": "36",
}

# status/outcome word -> styles. One place so runs/show/run agree.
_STATUS_STYLES = {
    "ok": ("green",),
    "passed": ("green",),
    "failed": ("red",),
    "error": ("red",),
    "unavailable": ("yellow",),
}


def color_enabled(stream: TextIO | None = None) -> bool:
    """Whether it is safe to emit ANSI color to ``stream`` (default stdout).

    Off unless the stream is a real terminal; ``NO_COLOR`` (set to anything,
    per no-color.org) and ``TERM=dumb`` force it off; ``FORCE_COLOR`` forces it
    on except when ``NO_COLOR`` also wins.
    """
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    stream = sys.stdout if stream is None else stream
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def paint(
    text: str,
    *styles: str,
    stream: TextIO | None = None,
    enabled: bool | None = None,
) -> str:
    """Wrap ``text`` in the given styles, or return it unchanged when color is
    off. ``enabled`` overrides the stream check (so a caller can decide once)."""
    use = color_enabled(stream) if enabled is None else enabled
    if not use or not styles:
        return text
    codes = ";".join(_CODES[s] for s in styles if s in _CODES)
    if not codes:
        return text
    return f"\033[{codes}m{text}\033[0m"


def status_styles(status: str) -> tuple[str, ...]:
    """The styles for a run/evidence status word (empty tuple if unknown)."""
    return _STATUS_STYLES.get(status, ())
