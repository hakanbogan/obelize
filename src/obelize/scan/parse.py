"""Read a scanned file's bytes once and gate them; manifests read through `contents` too.

Bytes in, bytes out, never `str`: from a `str` libcst ignores the PEP 263 cookie and `compile()`
refuses a leading BOM; `read_text(errors="replace")` destroys non-ASCII.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, get_args

import libcst as cst

from obelize import fsutil
from obelize.models import BailCode, Config, Finding, ScanSpec
from obelize.verify import cheap

# Only `parsed` carries a tree; run.json's `files_parsed` counts it, round-trip failures included.
ReadStatus = Literal["parsed", "does_not_parse", "not_a_candidate", "not_read"]

# `limitations[].code` values: three bail codes, and `unreadable` from `Skipped.reason`.
ReadRefusal = Literal["file_too_large", "input_does_not_parse", "internal_error", "unreadable"]
READ_REFUSALS: frozenset[ReadRefusal] = frozenset(get_args(ReadRefusal))

# Recorded because the two parse gates can report different lines for the same file.
Gate = Literal["libcst", "compile"]

# The one file-wide bail a readable, parsable file can still carry.
ROUNDTRIP_BAIL: Final = "roundtrip_mismatch"

# Both parse gates' bail; the limitation names the gate. `Final`, not `BailCode`: the literal must
# type-check as both `Finding.bail` and `Limitation.code`.
PARSE_BAIL: Final = "input_does_not_parse"

# The bail of a file obelize itself raised on: reported as a refusal, never edited.
CRASH_BAIL: Final = "internal_error"

# Characters kept of a parser message: room for libcst's "expected one of ..." list, no more.
MESSAGE_LIMIT = 200

# Levels of nesting a file may have, as `_past_limit` counts them: an operand-chain level is one,
# and libcst's own nodes between a container and its items cost more. On the default stack libcst
# renders a level in two Python frames and gives out near 490; the scan's visitors use three and
# give out near 320 on a chain. `compile()` accepts a chain of thirteen thousand terms on some
# versions, and a dotted import of fifteen thousand names on all, and libcst's parser then dies
# with SIGSEGV, so a deeper file is refused before libcst sees it.
MAX_DEPTH: Final = 300

# What the report says of a file nested past `MAX_DEPTH`; its own sentence, since a newer Python
# does not help.
_DEEP: Final = (
    f"Refused by obelize: nested more than {MAX_DEPTH} levels deep (a long chain of operands, an "
    "`elif` ladder, a dotted name, brackets inside brackets), more than its tree walkers can "
    "follow."
)

# What the report says of a notebook that is not a list of cells whose sources are text.
NOTEBOOK: Final = (
    "Not a notebook obelize can read as code: its JSON is invalid, it holds no list of cells, or "
    "a cell's source is not text. It is not analysed, so it holds the pin where it names the "
    "library."
)

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
    "internal_error": (
        "obelize raised an unexpected error on this file, so it is reported and not edited. This "
        "is a defect in obelize: please report it."
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
        if (self.data is None) != (self.status == "not_read") and self.status != "not_a_candidate":
            raise ValueError(
                f"{self.path}: the bytes are absent exactly when the status is `not_read`, "
                f"or `not_a_candidate` when they were not kept; got status {self.status!r}"
            )
        refused = self.status in {"does_not_parse", "not_read"}
        if (len(self.limitations) == 1) != refused:
            raise ValueError(
                f"{self.path}: every refusal owes the report one row and nothing else "
                f"writes one, got {len(self.limitations)} with status {self.status!r}"
            )


@dataclass(frozen=True, slots=True)
class Notebook:
    """A notebook's code cells as the one module they run as, and where each starts."""

    source: bytes
    # The line of `source` each code cell starts on, and its place among all the notebook's cells,
    # counted from 1 as a person counts them.
    cells: tuple[tuple[int, int], ...]

    def cell(self, line: int) -> int:
        """The place of the cell that `line` of `source` is in."""
        return next(place for first, place in reversed(self.cells) if first <= line)


def notebook(data: bytes) -> Notebook | None:
    """A notebook's code cells as one module, or `None` where it is not a list of cells whose
    sources are text.

    A line magic (`%matplotlib inline`, `!pip install openai`) is no Python and becomes a `pass`
    where it stood, so the lines and the indent around it stay; a cell that starts with `%%` is
    not Python at all and is left out.
    """
    try:
        document = json.loads(data)
    except (ValueError, RecursionError):
        return None
    cells = document.get("cells") if isinstance(document, dict) else None
    if not isinstance(cells, list):
        return None
    lines: list[str] = []
    starts: list[tuple[int, int]] = []
    for place, cell in enumerate(cells, 1):
        if not isinstance(cell, dict):
            return None
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        if isinstance(source, list) and all(isinstance(part, str) for part in source):
            source = "".join(source)
        if not isinstance(source, str):
            return None
        if source.startswith("%%"):
            continue
        starts.append((len(lines) + 1, place))
        lines.extend(_magic(line) for line in source.split("\n"))
    return Notebook(("\n".join(lines) + "\n").encode(), tuple(starts))


def _magic(line: str) -> str:
    """`line`, or a `pass` at its indent where it is an IPython line magic or a shell escape."""
    body = line.lstrip()
    return line[: len(line) - len(body)] + "pass" if body.startswith(("!", "%")) else line


def candidate(data: bytes, tokens: tuple[str, ...]) -> bool:
    """Whether the raw bytes hold a prefilter token; tokens are ASCII, so nothing is decoded.

    Public: also asked of files `exclude` removed and of dependency manifests.
    """
    return any(token.encode("ascii") in data for token in tokens)


def gates(path: str, data: bytes, *, notebook: bool = False) -> Read:
    """Gate bytes, in order: `compile()` accepts, the nesting is within `MAX_DEPTH`, libcst parses,
    the bytes round-trip.

    `compile()` goes first because it answers a pathologically deep expression with an exception
    where libcst's parser overruns the C stack and kills the process; the depth check covers what
    it accepts. `compile()` refuses some libcst trees (a late `__future__` import, module-level
    `return`) and a failure of any is one never-edited `parse_error` finding. Round-trip is last:
    its failure (a lost bare-CR terminator, which compiles) leaves the file analysed but never
    written. `path` must be repo-relative: it lands in the exception's `.filename`. A notebook's
    cells may `await` at their top level, which a module may not.
    """
    flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT if notebook else 0
    try:
        # `dont_inherit`: this module's `from __future__ import annotations` is not the file's.
        compile(data, path, "exec", flags, dont_inherit=True)
    except cheap.COMPILE_REFUSALS as error:
        return does_not_parse(path, data, "compile", error)
    if (deep := _past_limit(data)) is not None:
        return _refused(path, data, *deep, PARSE_BAIL, _DEEP)
    try:
        module = cst.parse_module(data)
    except (cst.ParserSyntaxError, SyntaxError, ValueError) as error:
        return does_not_parse(path, data, "libcst", error)
    try:
        faithful = module.bytes == data
    except RecursionError as error:
        # libcst renders a tree one frame per level, so a very long chain overruns the stack.
        return does_not_parse(path, data, "libcst", error)
    return Read(
        path=path,
        status="parsed",
        data=data,
        module=module,
        bail=None if faithful else ROUNDTRIP_BAIL,
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
    """One file's bytes, or the row saying why not: where a scanned file is opened, but for one
    over the size limit that `installed` searches for a version, in windows, through `fsutil`.

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


# What a read of a scan goes through, so a caller may answer from bytes it already holds; the search
# of a file over the size limit is the one that does not.
Contents = Callable[[str], tuple[bytes | None, tuple[Limitation, ...]]]


def disk(root: Path, config: Config) -> Contents:
    """`contents` for one root and configuration, as the callable a scan reads through."""
    return lambda path: contents(root, path, config)


def _past_limit(data: bytes) -> tuple[int, int] | None:
    """The line and column where nesting passes `MAX_DEPTH`, or `None`.

    Walked without recursion, since the input is what overruns it.
    """
    try:
        stack: list[tuple[ast.AST, int]] = [(ast.parse(data), 0)]
        while stack:
            node, depth = stack.pop()
            if isinstance(node, ast.expr | ast.stmt | ast.alias) and (
                depth + _dots(node) > MAX_DEPTH
            ):
                return node.lineno, node.col_offset
            stack.extend((child, depth + step) for child, step in _children(node))
    except (RecursionError, MemoryError):  # building the tree already overran the stack
        return 1, 0
    return None


def _children(node: ast.AST) -> Iterator[tuple[ast.AST, int]]:
    """Each child of `node` with the levels it sits below it in libcst's tree, which `ast` hides.

    A field holding one node is a level, an index four. An item of a list costs three: a node of
    libcst's own (`Arg`, `Element`, `IndentedBlock`) and the frames its visitors spend on a
    sequence. The costs are measured, by `tests/unit/test_parse.py::SHAPES`.
    """
    for name, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            yield value, 4 if isinstance(node, ast.Subscript) and name == "slice" else 1
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, ast.AST):
                    yield item, _item(node, name, item)


def _item(node: ast.AST, field: str, item: ast.AST) -> int:
    """An `and` or `or` nests each operand one level a term, where `ast` holds them flat. An `elif`
    nests no more than the `if` above it, and starts in its column, where an `if` inside `else:` is
    indented; an `else` or `finally` is a node of its own more."""
    if isinstance(node, ast.BoolOp):
        return len(node.values) - 1
    if (
        isinstance(node, ast.If)
        and isinstance(item, ast.stmt)
        and field == "orelse"
        and item.col_offset == node.col_offset
    ):
        return 1
    return 4 if field in {"orelse", "finalbody"} else 3


def _dots(node: ast.AST) -> int:
    """Levels libcst nests in a dotted name that `ast` holds as one string: `a.b.c` is two."""
    match node:
        case ast.alias(name=name) | ast.ImportFrom(module=name) if name:
            return name.count(".")
    return 0


def does_not_parse(path: str, data: bytes, gate: Gate, error: Exception) -> Read:
    """The single finding and the row naming the gate; `evidence=None` so no line is quoted."""
    line, column = _coordinates(error)
    detail = f"{_DETAIL[PARSE_BAIL]} Refused by {gate}: {_message(error)}"
    return _refused(path, data, line, column, PARSE_BAIL, detail)


def crashed(path: str, data: bytes, error: Exception) -> Read:
    """The same refusal for a file obelize raised on; the row names the class, never the message.

    A message can quote the file or a path. The status stays `does_not_parse`: no tree reaches
    anything past this, so `files_parsed` does not count the file either.
    """
    return _refused(
        path, data, 1, 0, CRASH_BAIL, f"{_DETAIL[CRASH_BAIL]} It raised {type(error).__name__}."
    )


def _refused(
    path: str,
    data: bytes,
    line: int,
    column: int,
    code: Literal["input_does_not_parse", "internal_error"],
    detail: str,
) -> Read:
    finding = Finding(
        path=path,
        line=line,
        column=column,
        kind="parse_error",
        confidence_reason="parse_error",
        symbol=None,
        evidence=None,
        scan_status="unsupported",
        bail=code,
    )
    return Read(
        path=path,
        status="does_not_parse",
        data=data,
        findings=(finding,),
        limitations=(Limitation(path=path, code=code, detail=detail),),
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
        text = str(error) or type(error).__name__
    first = (text.splitlines() or [""])[0].strip()
    return first if len(first) <= MESSAGE_LIMIT else first[: MESSAGE_LIMIT - 3] + "..."


def limitation(path: str, code: ReadRefusal, extra: str = "") -> Limitation:
    """A run.json row from `_DETAIL`; the only other writer is `runtime.declaration`."""
    sentence = _DETAIL[code]
    return Limitation(path=path, code=code, detail=f"{sentence} {extra}" if extra else sentence)


__all__ = [
    "CRASH_BAIL",
    "MAX_DEPTH",
    "MESSAGE_LIMIT",
    "NOTEBOOK",
    "PARSE_BAIL",
    "READ_REFUSALS",
    "ROUNDTRIP_BAIL",
    "Gate",
    "Limitation",
    "Notebook",
    "Read",
    "ReadRefusal",
    "ReadStatus",
    "candidate",
    "contents",
    "crashed",
    "does_not_parse",
    "gates",
    "limitation",
    "notebook",
    "read",
]
