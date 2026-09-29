"""The standard streams' encoding, which a redirected Windows stream takes from the code page."""

import sys

if sys.platform == "win32":
    from obelize.native.console_windows import utf8_stdio  # pragma: windows-only
else:
    from obelize.native.console_posix import utf8_stdio  # pragma: posix-only

__all__ = ["utf8_stdio"]
