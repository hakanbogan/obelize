"""Resource limits on Windows, which has no `setrlimit`."""

from __future__ import annotations

import sys

assert sys.platform == "win32"  # noqa: S101 - `mypy` for another platform reads no further


def limit() -> None:
    """Nothing to cap with: the parent's deadline is the limit, and it ends the process."""


__all__ = ["limit"]
