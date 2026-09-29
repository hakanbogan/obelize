"""The standard streams on POSIX, which encode as the locale says."""

from __future__ import annotations

import sys

assert sys.platform != "win32"  # noqa: S101 - `mypy --platform win32` reads no further


def utf8_stdio() -> None:
    """Nothing to change: the locale is UTF-8 by default, and PEP 538 coerces the C locale."""


__all__ = ["utf8_stdio"]
