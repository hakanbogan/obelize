"""`patch.diff`: a git-compatible unified diff that Obelize writes but never applies or reverses.

Bytes are never decoded, so latin-1, CRLF, BOM and bare-CR files pass unchanged. Lines split on
`\\n` only, as git does (`bytes.splitlines` also splits on bare CR). Paths are quoted as git does:
a quote, backslash, control or non-ASCII byte is C-quoted; a space is not, but `---`/`+++` get a
trailing tab. No `index` line: git apply needs none, and a wrong blob hash breaks `--3way`.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Sequence

    from obelize.fsutil import Change

# Context lines either side, the `diff -u` and git default.
CONTEXT = 3

# Git's marker for a last line without terminator; appliers read it.
NO_NEWLINE = b"\\ No newline at end of file\n"

# Bytes git escapes by name; other non-printables go through `\ooo`.
_NAMED: dict[int, bytes] = {
    0x07: rb"\a",
    0x08: rb"\b",
    0x09: rb"\t",
    0x0A: rb"\n",
    0x0B: rb"\v",
    0x0C: rb"\f",
    0x0D: rb"\r",
    0x22: rb"\"",
    0x5C: rb"\\",
}


@dataclass(frozen=True, slots=True)
class FilePatch:
    """One file's diff; `hunks` is counted here and recorded as `run.json` `file_edits[].hunks`."""

    path: str
    hunks: int
    text: bytes


def diff(changes: Iterable[Change]) -> tuple[FilePatch, ...]:
    """One `FilePatch` per changed file, in path order; unchanged files yield no entry.

    `file_edits` is read against this list, so an empty entry would claim a file the patch lacks.
    """
    return tuple(
        patch
        for patch in (
            _one(change.path, change.before, change.after)
            for change in sorted(changes, key=lambda change: change.path)
        )
        if patch is not None
    )


def render(patches: Sequence[FilePatch]) -> bytes:
    """Every file's diff in the given order; empty bytes when nothing changed."""
    return b"".join(patch.text for patch in patches)


def _one(path: str, before: bytes, after: bytes) -> FilePatch | None:
    if before == after:
        return None
    old, new = _lines(before), _lines(after)
    groups = SequenceMatcher(
        # autojunk skips lines in >1% of a 200+ line file (blank lines, `)`), bloating hunks.
        None,
        old,
        new,
        autojunk=False,
    ).get_grouped_opcodes(CONTEXT)
    body: list[bytes] = []
    count = 0
    for group in groups:
        count += 1
        body.append(_header(group))
        for tag, first, last, other_first, other_last in group:
            if tag == "equal":
                body.extend(_row(b" ", line) for line in old[first:last])
                continue
            if tag != "insert":
                body.extend(_row(b"-", line) for line in old[first:last])
            if tag != "delete":
                body.extend(_row(b"+", line) for line in new[other_first:other_last])
    return FilePatch(path=path, hunks=count, text=_preamble(path) + b"".join(body))


def _lines(data: bytes) -> list[bytes]:
    """Split on `\\n` alone, keeping terminators; only an unterminated last line lacks one."""
    if not data:
        return []
    parts = data.split(b"\n")
    tail = parts.pop()
    lines = [part + b"\n" for part in parts]
    if tail:
        lines.append(tail)
    return lines


def _row(prefix: bytes, line: bytes) -> bytes:
    if line.endswith(b"\n"):
        return prefix + line
    return prefix + line + b"\n" + NO_NEWLINE


def _header(group: Sequence[tuple[str, int, int, int, int]]) -> bytes:
    first, last = group[0], group[-1]
    old = _span(first[1], last[2])
    new = _span(first[3], last[4])
    return f"@@ -{old} +{new} @@\n".encode()


def _span(start: int, stop: int) -> str:
    """One header side: start line, plus length unless it is 1; an empty side starts a line early.

    No rule creates or deletes a file, but a header off by one applies in the wrong place.
    """
    length = stop - start
    if length == 1:
        return f"{start + 1}"
    return f"{start if not length else start + 1},{length}"


def _preamble(path: str) -> bytes:
    raw = path.encode("utf-8")
    if _awkward(raw):
        old, new, tab = _quote(b"a/" + raw), _quote(b"b/" + raw), b""
    else:
        old, new = b"a/" + raw, b"b/" + raw
        tab = b"\t" if b" " in raw else b""
    return b"diff --git " + old + b" " + new + b"\n--- " + old + tab + b"\n+++ " + new + tab + b"\n"


def _awkward(raw: bytes) -> bool:
    return any(byte < 0x20 or byte >= 0x7F or byte in {0x22, 0x5C} for byte in raw)


def _quote(raw: bytes) -> bytes:
    """git's `quote_c_style`."""
    out = bytearray(b'"')
    for byte in raw:
        named = _NAMED.get(byte)
        if named is not None:
            out += named
        elif byte < 0x20 or byte >= 0x7F:
            out += b"\\%03o" % byte
        else:
            out.append(byte)
    out += b'"'
    return bytes(out)


__all__ = ["CONTEXT", "NO_NEWLINE", "FilePatch", "diff", "render"]
