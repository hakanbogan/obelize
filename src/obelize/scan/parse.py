"""Read a scanned file's bytes once and gate them; manifests read through `contents` too.

Bytes in, bytes out, never `str`: from a `str` libcst ignores the PEP 263 cookie and `compile()`
refuses a leading BOM; `read_text(errors="replace")` destroys non-ASCII.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, get_args

import libcst as cst

from obelize import fsutil
from obelize.models import BailCode, Config, Finding, ScanSpec

# Only `parsed` carries a tree; run.json's `files_parsed` counts it, round-trip failures included.
ReadStatus = Literal["parsed", "does_not_parse", "not_a_candidate", "not_read"]

# `limitations[].code` values, none new: two existing bail codes, and `unreadable` from
# `Skipped.reason`.
ReadRefusal = Literal["file_too_large", "input_does_not_parse", "unreadable"]
READ_REFUSALS: frozenset[ReadRefusal] = frozenset(get_args(ReadRefusal))

# Recorded because the two parse gates can report different lines for the same file.
Gate = Literal["libcst", "compile"]

# The one file-wide bail a readable, parsable file can still carry.
ROUNDTRIP_BAIL: Final = "roundtrip_mismatch"

# Both parse gates' bail; the limitation names the gate. `Final`, not `BailCode`: the literal must
# type-check as both `Finding.bail` and `Limitation.code`.
PARSE_BAIL: Final = "input_does_not_parse"

# Characters kept of a parser message: room for libcst's "expected one of ..." list, no more.
MESSAGE_LIMIT = 200

# One report sentence per ReadRefusal; a test pins the key set.
_DETAIL: dict[ReadRefusal, str] = {
    "file_too_large": (
        "Larger than max_file_bytes, so it was not read. Raise the limit in "
        ".obelize.yml if this file is really source."
    ),
    "input_does_not_parse": (
        "Not valid Python for this interpreter, so it is reported and not edited. "
        "If it is valid on a newer Python, run obelize with that version."
    ),
    "unreadable": (
        "Selected but could not be opened: a permission problem, or the path became "
        "a symbolic link after it was selected. Check it before trusting the count."
    ),
}


@dataclass(frozen=True, slots=True)
class Limitation:
    """A run.json `limitations[]` row; `detail` may quote a parser, never a line of the file."""

    path: str
    code: ReadRefusal
    detail: str


@dataclass(frozen=True, slots=True)
class Read:
    """One file's read; `__post_init__` rejects field combinations that become silent zeros."""

    path: str
    status: ReadStatus
    data: bytes | None = None
    module: cst.Module | None = None
    # Carried by every finding and binding in the file: analysed, never written.
    bail: BailCode | None = None
    findings: tuple[Finding, ...] = ()
    limitations: tuple[Limitation, ...] = ()

    def __post_init__(self) -> None:
        if (self.module is not None) != (self.status == "parsed"):
            raise ValueError(
                f"{self.path}: a tree exists exactly when the status is `parsed`, "
                f"got status {self.status!r}"
            )
        if self.bail is not None and (self.status != "parsed" or self.bail != ROUNDTRIP_BAIL):
            raise ValueError(
                f"{self.path}: the only file-wide bail this module raises is "
                f"{ROUNDTRIP_BAIL!r} on a parsed file, got {self.bail!r} with status "
                f"{self.status!r}"
            )
        if (len(self.findings) == 1) != (self.status == "does_not_parse"):
            raise ValueError(
                f"{self.path}: a file that does not parse yields exactly one finding and "
                f"nothing else does, got {len(self.findings)} with status {self.status!r}"
            )
        if (self.data is None) != (self.status == "not_read"):
            raise ValueError(
                f"{self.path}: the bytes are absent exactly when the status is `not_read`, "
                f"got status {self.status!r}"
            )
        refused = self.status in {"does_not_parse", "not_read"}
        if (len(self.limitations) == 1) != refused:
            raise ValueError(
                f"{self.path}: every refusal owes the report one row and nothing else "
                f"writes one, got {len(self.limitations)} with status {self.status!r}"
            )


def candidate(data: bytes, tokens: tuple[str, ...]) -> bool:
    """Whether the raw bytes hold a prefilter token; tokens are ASCII, so nothing is decoded.

    Public: also asked of files `exclude` removed and of dependency manifests.
    """
    return any(token.encode("ascii") in data for token in tokens)


def gates(path: str, data: bytes) -> Read:
    """Gate bytes, in order: libcst parses, `compile()` accepts, the bytes round-trip.

    `compile()` refuses some libcst trees (a late `__future__` import, module-level `return`); a
    failure of either is one never-edited `parse_error` finding. Round-trip is last: its failure
    (a lost bare-CR terminator, which compiles) leaves the file analysed but never written.
    `path` must be repo-relative: it lands in the exception's `.filename`.
    """
    try:
        module = cst.parse_module(data)
    except (cst.ParserSyntaxError, SyntaxError, ValueError) as error:
        return _does_not_parse(path, data, "libcst", error)
    try:
        compile(data, path, "exec")
    except SyntaxError as error:
        return _does_not_parse(path, data, "compile", error)
    return Read(
        path=path,
        status="parsed",
        data=data,
        module=module,
        bail=None if module.bytes == data else ROUNDTRIP_BAIL,
    )


def read(root: Path, path: str, spec: ScanSpec, config: Config) -> Read:
    """Size, read, prefilter, gates: an oversized file is never read; most fail the prefilter."""
    data, limitations = contents(root, path, config)
    if data is None:
        return Read(path=path, status="not_read", limitations=limitations)
    if not candidate(data, spec.prefilter_tokens):
        return Read(path=path, status="not_a_candidate", data=data)
    return gates(path, data)


def contents(root: Path, path: str, config: Config) -> tuple[bytes | None, tuple[Limitation, ...]]:
    """One file's bytes, or the row saying why not: the only place a scanned file is opened.

    Manifests and the manifest pin check's excluded-file check use it too, so all share the
    size limit, the `O_NOFOLLOW` open and the `Limitation` vocabulary.
    """
    absolute = root / path
    try:
        size = absolute.lstat().st_size
    except OSError:
        return None, (limitation(path, "unreadable"),)
    if size > config.max_file_bytes:
        return None, (
            limitation(
                path,
                "file_too_large",
                f"It is {size} bytes against a limit of {config.max_file_bytes}.",
            ),
        )
    try:
        return fsutil.read(absolute), ()
    except OSError:
        return None, (limitation(path, "unreadable"),)


def _does_not_parse(path: str, data: bytes, gate: Gate, error: Exception) -> Read:
    """The single finding and the row naming the gate; `evidence=None` so no line is quoted."""
    line, column = _coordinates(error)
    finding = Finding(
        path=path,
        line=line,
        column=column,
        kind="parse_error",
        confidence_reason="parse_error",
        symbol=None,
        evidence=None,
        scan_status="unsupported",
        bail=PARSE_BAIL,
    )
    return Read(
        path=path,
        status="does_not_parse",
        data=data,
        findings=(finding,),
        limitations=(limitation(path, PARSE_BAIL, f"Refused by {gate}: {_message(error)}"),),
    )


def _coordinates(error: Exception) -> tuple[int, int]:
    """A 1-based line and 0-based column from whichever exception arrived.

    `cst.ParserSyntaxError` is not a `SyntaxError`, and `.raw_*` (not `.editor_*`) are its
    coordinates. `Finding.line` >= 1 needs the floors: a null byte gives `lineno=None`, an unknown
    cookie `lineno=0`.
    """
    if isinstance(error, cst.ParserSyntaxError):
        return max(1, error.raw_line), max(0, error.raw_column)
    if isinstance(error, SyntaxError):
        return max(1, error.lineno or 1), max(0, (error.offset or 1) - 1)
    return 1, 0


def _message(error: Exception) -> str:
    """The parser's first message line, capped, never a line of the file.

    `str(ParserSyntaxError)` and `SyntaxError.text` quote the source, so neither is used.
    `compile()` still quotes an unknown coding cookie: a declaration, kept to explain the refusal.
    """
    if isinstance(error, cst.ParserSyntaxError):
        text = error.message
    elif isinstance(error, SyntaxError):
        # Typed `str`, but `SyntaxError().msg` is `None`.
        text = error.msg or ""
    else:
        text = str(error)
    first = (text.splitlines() or [""])[0].strip()
    return first if len(first) <= MESSAGE_LIMIT else first[: MESSAGE_LIMIT - 3] + "..."


def limitation(path: str, code: ReadRefusal, extra: str = "") -> Limitation:
    """A run.json row from `_DETAIL`; the only other writer is `runtime.declaration`."""
    sentence = _DETAIL[code]
    return Limitation(path=path, code=code, detail=f"{sentence} {extra}" if extra else sentence)


__all__ = [
    "MESSAGE_LIMIT",
    "PARSE_BAIL",
    "READ_REFUSALS",
    "ROUNDTRIP_BAIL",
    "Gate",
    "Limitation",
    "Read",
    "ReadRefusal",
    "ReadStatus",
    "candidate",
    "contents",
    "gates",
    "limitation",
    "read",
]
