"""`external_fixer`: a maintained tool's rewrite, held to the proof of a rule's own.

The tool runs on a file after every other rule of the pack has written it, over their output, and
what it prints is kept only when all of this holds (ADR-074):

- it changed no line but those of the rows the pack's symbols claim, mapped back to the file as
  the scan read it, so it changed none a rule of the pack wrote; it added only imports, and wrote no
  line wider than the pack's layout (a line already that wide is let by);
- run again on its own output it changed nothing;
- no name an import it added binds is a local of a function, class or comprehension of the file,
  where the call it wrote would read the local and not the import;
- the scan of its output finds none of the claimed symbols: a tool that leaves an import of a
  removed name, or skips a use, has not migrated the file.

The output then goes through the driver's gates as any rule's does. A refusal withholds the claimed
rows, so by atomicity the file stays as it was.
"""

from __future__ import annotations

import ast
import hashlib
import re
import symtable
import textwrap
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar

from obelize.models import BailCode, Edit
from obelize.scan import runner as scanner
from obelize.transforms import fixers
from obelize.transforms.base import BailError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from obelize.models import Finding, FixerId, ScanSpec
    from obelize.packs.schema import ChangeKind, ExternalFixerChange
    from obelize.scan.runner import FileResult
    from obelize.transforms.base import RuleContext

# Codes this rule raises itself; the tool's own are `fixers`'s.
BAILS: frozenset[BailCode] = frozenset(
    {
        "external_tool_missing",
        "external_tool_version_unsupported",
        "external_tool_failed",
        "external_tool_timeout",
        "external_tool_size_limit",
        "external_fix_out_of_scope",
        "external_fix_incomplete",
        "external_fix_not_idempotent",
    }
)


class ExternalFixer:
    kind: ClassVar[ChangeKind] = "external_fixer"

    def __init__(self, change: ExternalFixerChange) -> None:
        self.id = change.id
        self.fixer: FixerId = change.params.fixer
        self._symbols = change.params.symbols

    @property
    def consumes(self) -> frozenset[str]:
        """Nothing: the tool decides what happens to an import, and the proof reads the result."""
        return frozenset()

    @property
    def client_readers(self) -> frozenset[str]:
        return frozenset()

    def claims(self, finding: Finding) -> bool:
        symbol = finding.symbol or ""
        return any(symbol == named or symbol.startswith(f"{named}.") for named in self._symbols)

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        """Nothing is recorded in the tree: the tool works on the bytes the other rules wrote, in
        `fix`, which the driver calls after them."""
        return ()


@dataclass(frozen=True, slots=True)
class Fix:
    """One run of a tool over one file, as `run.json` records it."""

    fixer: FixerId
    path: str
    version: str
    before_sha256: str
    after_sha256: str
    lines: int


@dataclass(frozen=True, slots=True)
class Fixed:
    """The bytes after every fixer, the rows of the claimed findings, what was refused (by
    `id(finding)`) and each run."""

    after: bytes
    edits: tuple[Edit, ...]
    withheld: dict[int, BailCode]
    ran: tuple[Fix, ...]


def fix(
    rules: Sequence[ExternalFixer],
    result: FileResult,
    data: bytes,
    produced: bytes,
    spec: ScanSpec,
    width: int,
    *,
    live: bool,
) -> Fixed:
    """Each fixer in turn over `produced`, the other rules' output for `data`.

    Not `live`, because another row of the file is withheld already or the file does not read back
    as it is, no tool runs: the rows are `auto` as any rule's are, and the driver withholds them.
    """
    name = PurePosixPath(result.path).name
    current, origin = produced, _carry(list(range(1, len(_lines(data)) + 1)), data, produced)
    edits: list[Edit] = []
    withheld: dict[int, BailCode] = {}
    ran: list[Fix] = []
    for rule in rules:
        mine = [
            row
            for row in result.plan.findings
            if row.scan_status == "eligible" and rule.claims(row)
        ]
        refused: dict[int, BailCode] = {}
        if live and mine:
            try:
                made = fixers.run(rule.fixer, name, current)
                proved = _proof(rule, mine, result.path, current, origin, made, spec, width)
            except BailError as bail:
                refused = {id(row): bail.reason for row in mine}
            else:
                refused, lines = proved
                ran.append(
                    Fix(
                        rule.fixer,
                        result.path,
                        made.version,
                        _hash(current),
                        _hash(made.output),
                        lines,
                    )
                )
                if not refused:
                    origin, current = _carry(origin, current, made.output), made.output
        withheld.update(refused)
        edits.extend(
            Edit(path=result.path, line=row.line, status="auto", rule_id=rule.id)
            if id(row) not in refused
            else Edit(
                path=result.path,
                line=row.line,
                status="needs_review",
                rule_id=rule.id,
                reason=refused[id(row)],
            )
            for row in mine
        )
    return Fixed(produced if withheld else current, tuple(edits), withheld, tuple(ran))


def _proof(
    rule: ExternalFixer,
    mine: Sequence[Finding],
    path: str,
    current: bytes,
    origin: list[int | None],
    made: fixers.Ran,
    spec: ScanSpec,
    width: int,
) -> tuple[dict[int, BailCode], int]:
    """The rows the output does not hold for, and the lines it changed."""
    old, new = _lines(current), _lines(made.output)
    changed, legal = _hunks(old, new, origin, {row.line for row in mine}, width)
    if not legal:
        return _all(mine, "external_fix_out_of_scope"), changed
    if made.output == current:
        return _all(mine, "external_fix_incomplete"), 0
    if fixers.run(rule.fixer, PurePosixPath(path).name, made.output).output != made.output:
        return _all(mine, "external_fix_not_idempotent"), changed
    added = Counter(_imported(made.output)) - Counter(_imported(current))
    if added and _shadowed(made.output, set(added)):
        return _all(mine, "external_fix_out_of_scope"), changed
    candidate = scanner.Candidate(path, _hash(made.output), made.output)
    left = {
        row.symbol
        for row in scanner.examine(candidate, spec).plan.findings
        if row.scan_status != "not_a_usage" and rule.claims(row)
    }
    if not left:
        return {}, changed
    stuck = [row for row in mine if row.symbol in left] or list(mine)
    return _all(stuck, "external_fix_incomplete"), changed


def _hunks(
    old: list[bytes], new: list[bytes], origin: list[int | None], allowed: set[int], width: int
) -> tuple[int, bool]:
    """The lines `new` changes of `old`, and whether it changes only lines it may.

    A line it replaces or deletes must be one the scan reported (`allowed`) and no rule wrote. A
    block that grows past the lines it replaces adds, at its start or its end, only imports, blank
    lines and comments. A line it writes is no wider than `width`, unless a line it replaces
    already was.
    """
    changed, legal = 0, True
    for tag, first, last, other_first, other_last in _matcher(old, new).get_opcodes():
        if tag == "equal":
            continue
        added = new[other_first:other_last]
        replaced = old[first:last]
        extra = len(added) - len(replaced)
        changed += max(len(replaced), len(added))
        legal = legal and (
            all(one in allowed for one in origin[first:last])
            and (extra <= 0 or _imports(added[:extra]) or _imports(added[-extra:]))
            and (any(_width(line) >= width for line in replaced) or _fits(added, width))
        )
    return changed, legal


def _all(rows: Sequence[Finding], code: BailCode) -> dict[int, BailCode]:
    return {id(row): code for row in rows}


def _lines(data: bytes) -> list[bytes]:
    """Split on `\\n` alone, as `patch.diff` and git do, keeping the terminators."""
    return re.findall(rb"[^\n]*\n|[^\n]+", data)


def _matcher(old: list[bytes], new: list[bytes]) -> SequenceMatcher[bytes]:
    """The differ of two files' lines, as `patch.diff` has it: no junk heuristic below its size."""
    return SequenceMatcher(None, old, new, autojunk=len(old) * len(new) > 4_000_000)


def _carry(origin: list[int | None], before: bytes, after: bytes) -> list[int | None]:
    """For each line of `after`, the line of the scanned file it is, or `None` where it was
    written: `origin` is that for each line of `before`."""
    old, new = _lines(before), _lines(after)
    carried: list[int | None] = [None] * len(new)
    for first, second, size in _matcher(old, new).get_matching_blocks():
        carried[second : second + size] = origin[first : first + size]
    return carried


def _imports(added: Sequence[bytes]) -> bool:
    """Whether lines added between the scan's are import statements, and blank lines or comments."""
    try:
        body = ast.parse(textwrap.dedent(b"".join(added).decode("utf-8"))).body
    except (SyntaxError, ValueError):
        return False
    return all(isinstance(node, ast.Import | ast.ImportFrom) for node in body)


def _imported(data: bytes) -> list[str]:
    """The names the import statements of a file bind, anywhere in it; none if it does not parse."""
    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError):
        return []
    return [
        (alias.asname or alias.name).partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    ]


def _shadowed(data: bytes, names: set[str]) -> bool:
    """Whether one of `names` is a local of some function, class or comprehension of the file: a
    read there is not a read of the import, and where the name is bound further down the scope, a
    call above it raises `UnboundLocalError`."""
    try:
        table = symtable.symtable(data.decode("utf-8"), "<output>", "exec")
    except (SyntaxError, ValueError):
        return False
    return any(
        (symbol := scope.lookup(name)).is_local() or symbol.is_assigned()
        for scope in _scopes(table)
        for name in names & set(scope.get_identifiers())
    )


def _scopes(table: symtable.SymbolTable) -> list[symtable.SymbolTable]:
    return [inner for child in table.get_children() for inner in (child, *_scopes(child))]


def _fits(lines: Sequence[bytes], width: int) -> bool:
    return all(_width(line) <= width for line in lines)


def _width(line: bytes) -> int:
    """Characters, not bytes: a line of `é` is as wide as one of `e`."""
    return len(line.rstrip(b"\r\n").decode("utf-8", "replace"))


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = ["BAILS", "ExternalFixer", "Fix", "Fixed", "fix"]
