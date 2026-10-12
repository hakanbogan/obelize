"""`compile()` over every changed `.py` file as it now is on disk; no repository can turn it off.

Re-reading via `fsutil.read` (`O_NOFOLLOW`) catches what the codemod's parse gate cannot: a
cut-short write, a misplaced rename, an editor's save. A failure is `fail`: the one verification
verdict that needs no command configured, checked before any command runs, by the same
interpreter that accepted the input.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from pathlib import Path

from obelize import fsutil

# What `compile()` raises for rejected source, a NUL byte included (only pre-3.12 used ValueError);
# a deeply nested expression overruns the parser's stack or memory instead.
COMPILE_REFUSALS = (SyntaxError, RecursionError, MemoryError)


def compiles(data: bytes, path: str) -> None:
    """`compile()` for its verdict alone. A `SyntaxWarning` (an invalid escape, `is` with a
    literal) is the author's, and would quote their line on stderr."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        compile(data, path, "exec")


def refusal(root: Path, path: str) -> str | None:
    """Why this file does not compile or cannot be read, or `None` when it compiles.

    Worded with the relative `path`, never the exception's rendering: that names only the basename,
    and `error.filename` would carry an absolute path into evidence attached to public issues.
    A NUL-byte refusal has no line number.
    """
    try:
        compiles(fsutil.read(root / path), path)
    except COMPILE_REFUSALS as error:
        line = getattr(error, "lineno", None)
        return f"{path}:{line}: {_said(error)}" if line else f"{path}: {_said(error)}"
    except OSError as error:
        return f"{path} cannot be read: {error.strerror}"
    return None


def _said(error: BaseException) -> str:
    """The message without the "(app.py, line 1)" `str()` appends, which names the wrong path."""
    return str(getattr(error, "msg", None) or error) or type(error).__name__


def uncompilable(root: Path, paths: Iterable[str]) -> tuple[str, ...]:
    """Which of these relative paths do not compile, sorted; non-`.py` files are skipped."""
    return tuple(
        sorted(path for path in paths if path.endswith(".py") and refusal(root, path) is not None)
    )


__all__ = ["COMPILE_REFUSALS", "compiles", "refusal", "uncompilable"]
