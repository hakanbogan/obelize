"""Read dependency manifests and grade the pin edits on them.

Names match by PEP 503 `canonicalize_name`, never substring. Files are read as lines, never
round-tripped (that would reformat them), so the recorded address is the one the edit uses.
"""

from __future__ import annotations

import ast
import fnmatch
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, Literal

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from obelize.models import (
    REPO_ATOMICITY_BAIL,
    BailCode,
    ConfidenceReason,
    Finding,
    FindingKind,
    ImpactPlan,
    ManifestPlan,
    ScanSpec,
)
from obelize.scan import parse

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Iterator, Sequence
    from pathlib import Path

    from obelize.models import Config

# Every bail raised here, unranked: no two can fire on the same row.
BAILS: frozenset[BailCode] = frozenset(
    {"manifest_code_mismatch", REPO_ATOMICITY_BAIL, "transitive_dependency_in_use"}
)

# Keeps a legacy pin for a module only it installs; asked once nothing imports the legacy one.
TRANSITIVE_BAIL: Final[BailCode] = "transitive_dependency_in_use"

# Only `setup_py` is Python.
Layout = Literal["requirements", "toml", "cfg", "setup_py"]

# Exact basenames. No lockfiles, deliberately: a line edit would break their hashes.
NAMES: Final[dict[str, Layout]] = {
    "Pipfile": "toml",
    "pyproject.toml": "toml",
    "setup.cfg": "cfg",
    "setup.py": "setup_py",
}

REQUIREMENTS_GLOB: Final = "requirements*.txt"

# `requirements/*.txt`, which the glob misses; a pin missed there reads as nothing to do.
REQUIREMENTS_DIRECTORY: Final = "requirements"

SETUP_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"extras_require", "install_requires", "setup_requires", "tests_require"}
)

# Every row's kind and reason; `Finding` requires the two together.
KIND: Final[FindingKind] = "manifest"
REASON: Final[ConfidenceReason] = "manifest_dependency"

# Kinds that load the legacy distribution at run time, so its pin must stay. `parse_error` fails
# closed; a prose mention does not count. Public: `transforms/codemod.py` asks the same question.
IMPORTING: Final[frozenset[FindingKind]] = frozenset(
    {"dynamic", "import", "parse_error", "star_import"}
)

# The one `text_mention` that loads the module: `mock.patch("google.generativeai.X")` imports it.
_LIVE_MENTION: Final[ConfidenceReason] = "mock_patch_target"

# Stripped before a column is taken; a BOM is not whitespace to `str.strip`.
_BLANK: Final = " \t﻿"


@dataclass(frozen=True, slots=True)
class Declaration:
    """One declared dependency: canonical `name`; `raw` as written, from `column` to `end`.

    `pin` spans the version, or is `None` for extras, a URL or a non-string value a rewrite cannot
    carry; the rule refuses such a row and the scan still reports it.
    """

    path: str
    line: int
    column: int
    name: str
    raw: str
    end: int
    pin: tuple[int, int] | None


@dataclass(frozen=True, slots=True)
class Reading:
    """One manifest, read. A refusal produces no declarations and one row."""

    path: str
    declarations: tuple[Declaration, ...] = ()
    limitations: tuple[parse.Limitation, ...] = ()


@dataclass(frozen=True, slots=True)
class Migration:
    """What the per-file plans came to for the pin edits: lists, since the report must name
    the files."""

    # In-scope files with an edit; under the `atomic` policy, the files that migrate.
    migrated: tuple[str, ...] = ()
    blocking: tuple[str, ...] = ()
    # Removed by the user's `exclude`, yet naming the distribution.
    excluded: tuple[str, ...] = ()
    # (file, distribution) per import of a module only the legacy distribution installed.
    transitive: tuple[tuple[str, str], ...] = ()


def layout(path: str) -> Layout | None:
    """How to read `path`, or `None` when it is not a manifest at all."""
    name = PurePosixPath(path).name
    if name in NAMES:
        return NAMES[name]
    # `fnmatchcase`: `fnmatch` folds case on Windows only, and the answer must not vary by OS.
    if not fnmatch.fnmatchcase(name, "*.txt"):
        return None
    if fnmatch.fnmatchcase(name, REQUIREMENTS_GLOB):
        return "requirements"
    parent = PurePosixPath(path).parent.name
    return "requirements" if parent == REQUIREMENTS_DIRECTORY else None


def is_manifest(path: str) -> bool:
    return layout(path) is not None


def read(root: Path, path: str, config: Config) -> Reading:
    """Read one manifest under `root`, through the source files' size limit."""
    data, limitations = parse.contents(root, path, config)
    if data is None:
        return Reading(path=path, limitations=limitations)
    return Reading(path=path, declarations=declarations(path, data))


def declarations(path: str, data: bytes) -> tuple[Declaration, ...]:
    """Every declared dependency, in order; deliberately spec-free so nothing is filtered early."""
    found = layout(path)
    if found is None:  # pragma: no cover - callers ask `is_manifest` first
        return ()
    if found == "setup_py":
        return tuple(_from_setup_py(path, data))
    lines = data.decode("utf-8", "surrogateescape").split("\n")
    readers = {"requirements": _from_requirements, "toml": _from_toml, "cfg": _from_cfg}
    return tuple(readers[found](path, lines))


def survey(
    plans: Iterable[ImpactPlan],
    excluded: Iterable[str] = (),
    unanalysed: Iterable[str] = (),
    transitive: Iterable[tuple[str, str]] = (),
) -> Migration:
    """The pin-edit conditions from the per-file plans, plus two lists no plan carries.

    A file migrated if any row is eligible; it blocks if a non-eligible row still loads the
    distribution (`IMPORTING` or a mock target). `unanalysed` files block like an import.
    """
    migrated: set[str] = set()
    blocking: set[str] = set()
    for plan in plans:
        for row in plan.findings:
            if row.scan_status == "eligible":
                migrated.add(plan.path)
            elif row.kind in IMPORTING or row.confidence_reason == _LIVE_MENTION:
                blocking.add(plan.path)
    blocking.update(unanalysed)
    return Migration(
        migrated=tuple(sorted(migrated)),
        blocking=tuple(sorted(blocking)),
        excluded=tuple(sorted(set(excluded))),
        transitive=tuple(sorted(set(transitive))),
    )


def provided(path: str, data: bytes, spec: ScanSpec) -> tuple[tuple[str, str], ...]:
    """(path, distribution) per real import, not mention, of a module only the legacy one installed.

    An unparsable file yields nothing; the scan reports it elsewhere.
    """
    if not any(row.module.rpartition(".")[2].encode() in data for row in spec.transitive_modules):
        return ()
    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError):
        return ()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    return tuple(
        sorted(
            {
                (path, row.distribution)
                for row in spec.transitive_modules
                for name in imported
                if name == row.module or name.startswith(f"{row.module}.")
            }
        )
    )


def prefiltered(
    root: Path, paths: Iterable[str], spec: ScanSpec, config: Config
) -> tuple[tuple[str, ...], tuple[parse.Limitation, ...]]:
    """Excluded files matching the byte prefilter, named because the install they break is not.

    Bytes only: no parse and no finding, so an excluded file never returns as a review item.
    """
    hits: list[str] = []
    limitations: list[parse.Limitation] = []
    for name in sorted(paths):
        data, refused = parse.contents(root, name, config)
        limitations.extend(refused)
        if data is not None and parse.candidate(data, spec.prefilter_tokens):
            hits.append(name)
    return tuple(hits), tuple(limitations)


def plan(found: Sequence[Declaration], migration: Migration, spec: ScanSpec) -> ManifestPlan:
    """Grade every declaration against the pin-edit rule and the state of the code."""
    legacy = canonicalize_name(spec.legacy_distribution)
    new = canonicalize_name(spec.new_distribution)
    declares: dict[str, set[str]] = {}
    for declaration in found:
        declares.setdefault(declaration.path, set()).add(declaration.name)
    everywhere = {declaration.name for declaration in found}
    needed = tuple(
        sorted(
            {
                path
                for path, distribution in migration.transitive
                if canonicalize_name(distribution) not in everywhere
            }
        )
    )
    rows: list[Finding] = []
    for declaration in found:
        beside = declares[declaration.path]
        if declaration.name == legacy:
            rows.extend(_legacy(declaration, migration, spec, new in beside, needed))
        elif declaration.name == new and migration.blocking and legacy not in beside:
            rows.append(_row(declaration, spec.new_distribution, "manifest_code_mismatch"))
    return ManifestPlan(
        findings=tuple(sorted(rows, key=lambda row: row.sort_key)),
        blocking=migration.blocking,
        excluded=migration.excluded,
        transitive=needed,
    )


def _legacy(
    declaration: Declaration,
    migration: Migration,
    spec: ScanSpec,
    new_declared: bool,
    needed: Sequence[str],
) -> Iterator[Finding]:
    """The two pin edits on one legacy declaration, in its four states.

    Adding the new distribution is `auto` once anything migrated (a partial migration needs both);
    removing the legacy pin waits while any file imports it or needs a module only it installs.
    Both clear: one rewrite. Nothing migrated or importing: `not_a_usage` context, never an edit.
    """
    if not migration.migrated:
        code = REPO_ATOMICITY_BAIL if migration.blocking else None
        yield _row(declaration, spec.legacy_distribution, code, absent=code is None)
        return
    if not migration.blocking and not needed:
        # Both halves are clear, so they are one rewrite of one line.
        yield _row(declaration, spec.legacy_distribution, None)
        return
    if not new_declared:
        yield _row(declaration, spec.new_distribution, None)
    code = REPO_ATOMICITY_BAIL if migration.blocking else TRANSITIVE_BAIL
    yield _row(declaration, spec.legacy_distribution, code)


def _row(
    declaration: Declaration, symbol: str, bail: BailCode | None, *, absent: bool = False
) -> Finding:
    """One manifest finding; `absent` makes it context, not an edit."""
    status = "not_a_usage" if absent else "needs_review" if bail else "eligible"
    return Finding(
        path=declaration.path,
        line=declaration.line,
        column=declaration.column,
        kind=KIND,
        confidence_reason=REASON,
        symbol=symbol,
        evidence=None,
        scan_status=status,
        bail=bail,
    )


def _declare(path: str, line: int, column: int, text: str) -> Declaration | None:
    """One PEP 508 requirement, or None; the pin span comes from the same parse.

    A marker is cut at `;` and left in place; extras or a URL give no pin, as neither survives a
    change of distribution.
    """
    try:
        parsed = Requirement(text)
    except InvalidRequirement:
        return None
    written = parsed.name
    start = max(text.find(written), 0)
    end = column + start + len(written)
    rest = text[start + len(written) :]
    marker = rest.find(";")
    version = (rest if marker < 0 else rest[:marker]).rstrip()
    plain = not parsed.extras and parsed.url is None
    return Declaration(
        path=path,
        line=line,
        column=column + start,
        name=canonicalize_name(written),
        raw=written,
        end=end,
        pin=(end, end + len(version)) if plain else None,
    )


def _span(text: str) -> tuple[str, int]:
    """`text` without its surrounding blanks, and the column it starts at."""
    body = text.rstrip(_BLANK + "\r\n")
    column = len(body) - len(body.lstrip(_BLANK))
    return body[column:], column


def _uncommented(text: str) -> str:
    """Everything before a `#` outside quotes; ignored escapes misread only a TOML quoted quote."""
    quote = ""
    for index, character in enumerate(text):
        if quote:
            if character == quote:
                quote = ""
        elif character in "\"'":
            quote = character
        elif character == "#":
            return text[:index]
    return text


def _quoted(body: str, start: int) -> Iterator[tuple[int, str]]:
    """Every quoted string in `body` at or after `start`, with its column."""
    index = start
    while index < len(body):
        character = body[index]
        if character in "\"'":
            end = body.find(character, index + 1)
            if end < 0:
                return
            yield index + 1, body[index + 1 : end]
            index = end + 1
        else:
            index += 1


def _from_requirements(path: str, lines: list[str]) -> Iterator[Declaration]:
    """One PEP 508 requirement per line; `pip` options start with `-`, so PEP 508 rejects them."""
    for number, line in enumerate(lines, 1):
        body, column = _span(_uncommented(line))
        if not body:
            continue
        declaration = _declare(path, number, column, body)
        if declaration is not None:
            yield declaration


def _table(text: str) -> tuple[str, ...]:
    """The dotted key of a `[table]` or `[[array of tables]]` header."""
    inner = text.strip("[]").strip()
    return tuple(part.strip().strip("\"'") for part in inner.split("."))


def _is_dependency_table(table: tuple[str, ...]) -> bool:
    """A table whose *keys* are distribution names: Poetry and Pipenv."""
    if table in {("dev-packages",), ("packages",), ("tool", "poetry", "dependencies")}:
        return True
    if table == ("tool", "poetry", "dev-dependencies"):
        return True
    return (
        len(table) == 5 and table[:3] == ("tool", "poetry", "group") and table[4] == "dependencies"
    )


def _is_dependency_array(table: tuple[str, ...], key: str) -> bool:
    """PEP 621/735 requirement arrays; not `[build-system] requires`, which installs never read."""
    if table == ("project",):
        return key == "dependencies"
    return table in {("dependency-groups",), ("project", "optional-dependencies")}


def _value_pin(body: str, after: int) -> tuple[int, int] | None:
    """The span inside a TOML value that is exactly one quoted string, else `None`.

    Also refuses an unclosed quote (invalid TOML); an inner quote (triple-quoted, escaped) is fine.
    """
    rest = body[after:]
    value = rest.strip()
    quote = value[:1]
    if len(value) < 2 or quote not in "\"'" or value[-1] != quote:
        return None
    start = after + rest.index(quote) + 1
    return (start, start + len(value) - 2)


def _from_toml(path: str, lines: list[str]) -> Iterator[Declaration]:
    """`pyproject.toml` and `Pipfile`, read as lines.

    Under a dependency table the key is the distribution; in a dependency array each string is a
    requirement. An array closes by `[`/`]` depth, counted after comments are stripped.
    """
    table: tuple[str, ...] = ()
    depth = 0
    for number, line in enumerate(lines, 1):
        body = _uncommented(line)
        if depth > 0:
            yield from _array(path, number, body, 0)
            depth += body.count("[") - body.count("]")
            continue
        text, column = _span(body)
        if text.startswith("["):
            table = _table(text)
            continue
        cut = text.find("=")
        if cut < 0:
            continue
        key, offset = _span(text[:cut])
        if _is_dependency_table(table):
            quoted = key[:1] in "\"'"
            at = column + offset + (1 if quoted else 0)
            declaration = _declare(path, number, at, key.strip("\"'"))
            if declaration is not None:
                # The pin is inside the value's quotes; any other value shape (inline table,
                # array, multi-line string) gets none, so the rule refuses the row.
                yield replace(declaration, pin=_value_pin(body, column + cut + 1))
        elif _is_dependency_array(table, key.strip("\"'")):
            start = column + cut + 1
            yield from _array(path, number, body, start)
            depth = body.count("[", start) - body.count("]", start)


def _array(path: str, number: int, body: str, start: int) -> Iterator[Declaration]:
    for column, text in _quoted(body, start):
        declaration = _declare(path, number, column, text)
        if declaration is not None:
            yield declaration


def _cut(text: str) -> int:
    """The first `=` or `:`, which is how an INI file separates key from value."""
    cuts = [index for index in (text.find("="), text.find(":")) if index >= 0]
    return min(cuts) if cuts else -1


def _is_dependency_key(section: str, key: str) -> bool:
    if section == "options":
        return key in {"install_requires", "setup_requires", "tests_require"}
    return section == "options.extras_require"


def _from_cfg(path: str, lines: list[str]) -> Iterator[Declaration]:
    """`setup.cfg`: indented lines continue a value; only a line-initial `#` is a comment."""
    section = ""
    key = ""
    for number, line in enumerate(lines, 1):
        text, column = _span(line)
        if not text or text.startswith(("#", ";")):
            continue
        if line[:1] in " \t":
            if _is_dependency_key(section, key):
                declaration = _declare(path, number, column, text)
                if declaration is not None:
                    yield declaration
            continue
        if text.startswith("["):
            section, key = text.strip("[]").strip(), ""
            continue
        cut = _cut(text)
        if cut < 0:
            key = ""
            continue
        key = text[:cut].strip()
        value, offset = _span(text[cut + 1 :])
        if value and _is_dependency_key(section, key):
            declaration = _declare(path, number, column + cut + 1 + offset, value)
            if declaration is not None:
                yield declaration


class _Requirements(cst.CSTVisitor):
    """Literals under a `setup()` requirement keyword, except dict keys (an extra's name)."""

    def __init__(self) -> None:
        self.strings: list[cst.SimpleString] = []
        self._depth = 0
        self._keys = 0

    def visit_Arg(self, node: cst.Arg) -> None:
        if self._wanted(node):
            self._depth += 1

    def leave_Arg(self, node: cst.Arg) -> None:
        if self._wanted(node):
            self._depth -= 1

    def visit_DictElement_key(self, node: cst.DictElement) -> None:
        self._keys += 1

    def leave_DictElement_key(self, node: cst.DictElement) -> None:
        self._keys -= 1

    def visit_SimpleString(self, node: cst.SimpleString) -> None:
        if self._depth and not self._keys:
            self.strings.append(node)

    @staticmethod
    def _wanted(node: cst.Arg) -> bool:
        return node.keyword is not None and node.keyword.value in SETUP_KEYWORDS


def _from_setup_py(path: str, data: bytes) -> Iterator[Declaration]:
    """`setup.py`: only literals under requirement keywords declare; unparsable yields nothing."""
    try:
        module = cst.parse_module(data)
    except (cst.ParserSyntaxError, SyntaxError, ValueError):
        return
    # Without `unsafe_skip_copy` the wrapper deep-copies, and collected nodes lack positions.
    wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
    positions = wrapper.resolve(PositionProvider)
    collector = _Requirements()
    module.visit(collector)
    for node in collector.strings:
        text = node.evaluated_value
        if not isinstance(text, str):
            continue
        at = positions[node].start
        opening = len(node.prefix) + len(node.quote)
        declaration = _declare(path, at.line, at.column + opening, text)
        if declaration is None:
            continue
        # Spans are source columns only when the literal's bytes are its value; an escape (a
        # multi-line literal is an escaped newline) breaks that. The row stays; the pin goes.
        yield declaration if node.raw_value == text else replace(declaration, pin=None)


__all__ = [
    "BAILS",
    "IMPORTING",
    "KIND",
    "NAMES",
    "REASON",
    "REQUIREMENTS_DIRECTORY",
    "REQUIREMENTS_GLOB",
    "SETUP_KEYWORDS",
    "TRANSITIVE_BAIL",
    "Declaration",
    "Layout",
    "Migration",
    "Reading",
    "declarations",
    "is_manifest",
    "layout",
    "plan",
    "prefiltered",
    "provided",
    "read",
    "survey",
]
