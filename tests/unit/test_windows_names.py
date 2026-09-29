"""`native.windows_names`: the names Windows opens as something else, judged on any system.

Where Python has `ntpath.isreserved` (3.13 and later), each name's answer is checked against it
too, so the copied rules cannot drift from CPython's.
"""

from __future__ import annotations

import ntpath

import pytest

from obelize.native.windows_names import reserved

ISRESERVED = getattr(ntpath, "isreserved", None)

PORTS = [f"{port}{digit}" for port in ("COM", "LPT") for digit in "123456789\u00b9\u00b2\u00b3"]

RESERVED = [
    *("CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", *PORTS),
    "aux.py",
    "Aux.Py",
    "con.tar.gz",
    "nul .txt",
    "com\u00b9.py",
    "conout$.log",
    "app.py.",
    "app.py ",
    "pkg.",
    "...",
    "app.py:x",
    *(f"a{character}b.py" for character in '"*<>?|'),
    "a\x00b.py",
    "a\x1fb.py",
]

HELD = [
    "app.py",
    "console.py",
    "auxiliary.py",
    "nul_.py",
    "COM0",
    "COM10",
    "LPT0",
    "CONIN",
    ".hidden",
    " leading.py",
    "a b.py",
    "a\x7fb.py",
    ".",
    "..",
]


@pytest.mark.parametrize("name", RESERVED)
def test_a_name_windows_opens_as_something_else_is_reserved_wherever_it_sits(name: str) -> None:
    assert reserved(name)
    assert reserved(f"pkg/{name}")
    assert reserved(f"{name}/app.py")
    if ISRESERVED is not None:
        assert ISRESERVED(name)


@pytest.mark.parametrize("name", HELD)
def test_a_name_windows_holds_as_written_is_not_reserved(name: str) -> None:
    """`.` and `..` are the path guard's to refuse, not a name's."""
    assert not reserved(name)
    assert not reserved(f"pkg/{name}")
    if ISRESERVED is not None:
        assert not ISRESERVED(name)


@pytest.mark.parametrize("path", ["pkg\\app.py", "C:app.py", "c:/app.py"])
def test_a_backslash_or_a_drive_is_reserved_where_ntpath_reads_a_separator_or_a_drive(
    path: str,
) -> None:
    """`ntpath` has no name to judge here; on Windows `root / "C:app.py"` leaves the root."""
    assert reserved(path)
