"""Resource limits on POSIX, where `setrlimit` ends a process that outgrows them."""

from __future__ import annotations

import resource
import sys

assert sys.platform != "win32"  # noqa: S101 - `mypy --platform win32` reads no further

MEMORY_BYTES = 4 << 30
CPU_SECONDS = 300


def limit() -> None:
    """Cap this process's address space and CPU time. A limit the system refuses (macOS has no
    address-space cap) is left off and the other still set; the parent's deadline backs both."""
    for which, value in (
        (resource.RLIMIT_AS, MEMORY_BYTES),
        (resource.RLIMIT_CPU, CPU_SECONDS),
    ):
        try:
            resource.setrlimit(which, (value, value))
        except (ValueError, OSError):
            continue


__all__ = ["limit"]
