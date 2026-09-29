"""A checkout holds the bytes the index holds, whatever `core.autocrlf` the machine sets.

Answer keys, `.before`/`.after` pairs and the bundled pack are compared byte for byte, so a
checkout that turns LF into CRLF fails them for a reason that is not in the code.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _eol() -> list[tuple[str, str, str, str]]:
    """`git ls-files --eol` as (index, work tree, attributes, path) for every tracked file."""
    out = subprocess.run(
        ["git", "ls-files", "--eol", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    rows = []
    for record in out.split("\0")[:-1]:
        info, path = record.split("\t", 1)
        index, tree, attributes = info.split(maxsplit=2)
        rows.append((index, tree, attributes.strip(), path))
    return rows


def test_every_tracked_file_checks_out_with_the_line_endings_the_index_holds() -> None:
    differ = [
        f"{path}: {index} {tree}"
        for index, tree, _attributes, path in _eol()
        if index.removeprefix("i/") != tree.removeprefix("w/")
    ]
    assert not differ, differ


def test_every_file_checks_out_as_lf_or_unconverted_on_any_machine() -> None:
    """Without `core.autocrlf` the comparison above passes whatever the attributes say."""
    loose = [
        f"{path}: {attributes}"
        for _index, _tree, attributes, path in _eol()
        if attributes != "attr/-text" and not attributes.endswith(" eol=lf")
    ]
    assert not loose, loose


def test_a_file_the_index_holds_as_crlf_or_binary_is_never_converted() -> None:
    """Otherwise `git add --renormalize` would rewrite it to LF."""
    unmarked = [
        f"{path}: {index} {attributes}"
        for index, _tree, attributes, path in _eol()
        if index not in ("i/lf", "i/none") and attributes != "attr/-text"
    ]
    assert not unmarked, unmarked
