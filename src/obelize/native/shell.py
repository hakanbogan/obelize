"""An argument of a command obelize prints for the user to copy, and the examples it prints, as this
system's shells read them."""

import sys

if sys.platform == "win32":
    from obelize.native.windows_programs import quote  # pragma: windows-only
else:
    from shlex import quote  # pragma: posix-only

# A virtual environment's interpreter, and a shell to ask for: `cmd.exe` always exists.
VENV_PYTHON = ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"
SHELL = 'cmd /c "<command>"' if sys.platform == "win32" else "sh -c '<command>'"

__all__ = ["SHELL", "VENV_PYTHON", "quote"]
