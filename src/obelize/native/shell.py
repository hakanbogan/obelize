"""An argument of a command obelize prints for the user to copy, as this system's shells read it."""

import sys

if sys.platform == "win32":
    from obelize.native.windows_programs import quote  # pragma: windows-only
else:
    from shlex import quote  # pragma: posix-only

__all__ = ["quote"]
