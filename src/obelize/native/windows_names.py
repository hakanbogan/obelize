"""The names Windows cannot hold as written, by CPython 3.13's `ntpath.isreserved`.

3.12 has no `isreserved`, so its tables are copied here. Such a name opens something other than
the file it spells: `aux.py` a device, `app.py:x` a stream of `app.py`, `app.py.` the file
`app.py`, and `C:x` a file in another directory.
"""

from __future__ import annotations

# CPython's set without `/`, which splits the path before a name is judged.
_RESERVED_CHARACTERS = frozenset(
    {chr(code) for code in range(32)} | {'"', "*", ":", "<", ">", "?", "|", "\\"}
)

# The superscript digits are ports too.
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{digit}" for digit in "123456789\xb9\xb2\xb3"}
    | {f"LPT{digit}" for digit in "123456789\xb9\xb2\xb3"}
)


def reserved(path: str) -> bool:
    """Whether a component of this `/`-separated relative path is one Windows cannot hold."""
    return any(_reserved(name) for name in path.split("/"))


def _reserved(name: str) -> bool:
    if name[-1:] in (".", " "):
        return name not in (".", "..")
    if _RESERVED_CHARACTERS.intersection(name):
        return True
    # A device name before any extension, trailing spaces dropped: `nul .txt` too. Windows
    # versions disagree about some of these, and CPython refuses them all.
    return name.partition(".")[0].rstrip(" ").upper() in _RESERVED_NAMES


__all__ = ["reserved"]
