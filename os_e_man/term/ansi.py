"""Render rich Text to ANSI for a remote terminal."""

from __future__ import annotations

import io

from rich.console import Console
from rich.text import Text


def to_ansi(lines: list[Text], width: int = 100) -> str:
    """Render lines with styles as ANSI escape codes, '\\n' line endings (the ssh line
    editor turns those into CRLF). Long lines are soft-wrapped by the terminal itself,
    the way a real shell's output is."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="256", width=max(20, width),
                      legacy_windows=False, highlight=False, markup=False, emoji=False)
    for t in lines:
        console.print(t, soft_wrap=True)
    return buf.getvalue().replace("\r\n", "\n")


def style(text: str, spec: str, width: int = 100) -> str:
    """ANSI for a single fragment, without a trailing newline."""
    return to_ansi([Text(text, style=spec)], width)[:-1]
