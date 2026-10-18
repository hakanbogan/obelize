"""A cap on the memory and time of a child process that reads a stranger's files."""

import sys

if sys.platform == "win32":
    from obelize.native.limits_windows import limit  # pragma: windows-only
else:
    from obelize.native.limits_posix import limit  # pragma: posix-only

__all__ = ["limit"]
