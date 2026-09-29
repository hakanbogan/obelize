"""The standard streams on Windows, which encode in the ANSI code page when redirected."""

from __future__ import annotations

import io
import sys

assert sys.platform == "win32"  # noqa: S101 - `mypy` for another platform reads no further


def utf8_stdio() -> None:
    """Make stdout and stderr UTF-8, so a name outside the code page cannot fail a report.

    A new encoding alone would reset stderr's `backslashreplace` to `strict`.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors=stream.errors)


__all__ = ["utf8_stdio"]
