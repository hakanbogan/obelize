"""`compile()` over every changed `.py` file as it now is on disk; no repository can turn it off.

Re-reading via `fsutil.read` (`O_NOFOLLOW`) catches what the codemod's parse gate cannot: a
cut-short write, a misplaced rename, an editor's save. A failure is `fail`: the one verification
verdict that needs no command configured, checked before any command runs, by the same
interpreter that accepted the input.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from obelize import fsutil

# What `compile()` raises for rejected source, a NUL byte included (only pre-3.12 used ValueError).
COMPILE_REFUSALS = (SyntaxError,)


def refusal(root: Path, path: str) -> str | None:
    """Why this file does not compile or cannot be read, or `None` when it compiles.

    Worded with the relative `path`, never the exception's rendering: that names only the basename,
    and `error.filename` would carry an absolute path into evidence attached to public issues.
    A NUL-byte refusal has no line number.
    """
    try:
        compile(fsutil.read(root / path), path, "exec")
    except COMPILE_REFUSALS as error:
        line = getattr(error, "lineno", None)
        return f"{path}:{line}: {_said(error)}" if line else f"{path}: {_said(error)}"
    except OSError as error:
        return f"{path} cannot be read: {error.strerror}"
    return None


def _said(error: BaseException) -> str:
    """The message without the "(app.py, line 1)" `str()` appends, which names the wrong path."""
    return str(getattr(error, "msg", None) or error)


def uncompilable(root: Path, paths: Iterable[str]) -> tuple[str, ...]:
    """Which of these relative paths do not compile, sorted; non-`.py` files are skipped."""
    return tuple(
        sorted(path for path in paths if path.endswith(".py") and refusal(root, path) is not None)
    )


__all__ = ["COMPILE_REFUSALS", "refusal", "uncompilable"]
