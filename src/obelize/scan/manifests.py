"""Read dependency manifests and grade the pin edits on them.

Names match by PEP 503 `canonicalize_name`, never substring. Files are read as lines, never
round-tripped (that would reformat them), so the recorded address is the one the edit uses.
"""

from __future__ import annotations

import ast
import fnmatch
import re
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, Literal

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from obelize.models import (
    REPO_ATOMICITY_BAIL,
    BailCode,
    ConfidenceReason,
    Finding,
    FindingKind,
    ImpactPlan,
    ManifestPlan,
    ScanSpec,
    bounds,
)
from obelize.scan import parse

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Iterator, Sequence


# Every bail raised here, unranked: no two can fire on the same row.
BAILS: frozenset[BailCode] = frozenset(
    {"manifest_code_mismatch", REPO_ATOMICITY_BAIL, "transitive_dependency_in_use"}
)

# A pin the rule cannot write (extras, a URL). The rule raises it, and the corpus grades it there;
# here only a pack whose one distribution holds both APIs does, since its files wait on the pin.
SHAPE_BAIL: Final[BailCode] = "manifest_pin_shape_unsupported"

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
    carry; the rule refuses such a row and the scan still reports it. `spec` is the version as
    declared (a PEP 508 set, or Poetry's or Pipenv's string), `None` when it cannot be read.
    """

    path: str
    line: int
    column: int
    name: str
    raw: str
    end: int
    pin: tuple[int, int] | None
    spec: str | None


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


def read(path: str, contents: parse.Contents) -> Reading:
    """Read one manifest, through the source files' size limit."""
    data, limitations = contents(path)
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


def coupled(spec: ScanSpec) -> bool:
    """Whether the new SDK is the legacy distribution itself, one pin for both APIs."""
    return canonicalize_name(spec.legacy_distribution) == canonicalize_name(spec.new_distribution)


def survey(
    plans: Iterable[ImpactPlan],
    excluded: Iterable[str] = (),
    unanalysed: Iterable[str] = (),
    transitive: Iterable[tuple[str, str]] = (),
    *,
    paired: bool = False,
) -> Migration:
    """The pin-edit conditions from the per-file plans, plus two lists no plan carries.

    A file migrated if any row is eligible; it blocks if a non-eligible row still loads the
    distribution (`IMPORTING` or a mock target). `unanalysed` files block like an import. Where
    `paired` (see `coupled`) no import marks the old API, so any withheld row blocks.
    """
    migrated: set[str] = set()
    blocking: set[str] = set()
    for plan in plans:
        for row in plan.findings:
            if row.scan_status == "eligible":
                migrated.add(plan.path)
            elif (
                row.kind in IMPORTING
                or row.confidence_reason == _LIVE_MENTION
                or (paired and row.scan_status != "not_a_usage")
            ):
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
    paths: Iterable[str], spec: ScanSpec, contents: parse.Contents
) -> tuple[tuple[str, ...], tuple[parse.Limitation, ...]]:
    """Excluded files matching the byte prefilter, named because the install they break is not.

    Bytes only: no parse and no finding, so an excluded file never returns as a review item.
    """
    hits: list[str] = []
    limitations: list[parse.Limitation] = []
    for name in sorted(paths):
        data, refused = contents(name)
        limitations.extend(refused)
        if data is not None and parse.candidate(data, spec.prefilter_tokens):
            hits.append(name)
    return tuple(hits), tuple(limitations)


def merged(plans: Sequence[ManifestPlan]) -> ManifestPlan:
    """Several packs' verdicts on one repository: every row, and every file any of them named."""
    return ManifestPlan(
        findings=tuple(sorted((row for p in plans for row in p.findings), key=_by_position)),
        blocking=tuple(sorted({name for p in plans for name in p.blocking})),
        excluded=tuple(sorted({name for p in plans for name in p.excluded})),
        transitive=tuple(sorted({name for p in plans for name in p.transitive})),
    )


def _by_position(row: Finding) -> tuple[str, int, int, str, str]:
    return row.sort_key


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
            if not _arrived(declaration, spec):
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
    if spec.new_range is not None and declaration.pin is None:
        yield _row(declaration, spec.legacy_distribution, SHAPE_BAIL)
        return
    if not migration.blocking and not needed:
        # Both halves are clear, so they are one rewrite of one line.
        yield _row(declaration, spec.legacy_distribution, None)
        return
    if not new_declared:
        yield _row(declaration, spec.new_distribution, None)
    code = REPO_ATOMICITY_BAIL if migration.blocking else TRANSITIVE_BAIL
    yield _row(declaration, spec.legacy_distribution, code)


def _arrived(declaration: Declaration, spec: ScanSpec) -> bool:
    """Whether a declaration of the one distribution already pins the new range: no edit of it.

    The first version it admits decides, so `>=2` is on the new side and `>=0.28,<3` is not.
    """
    floor = lowest(declaration.spec)
    return (
        spec.new_range is not None
        and floor is not None
        and SpecifierSet(spec.new_range).contains(floor, prereleases=True)
    )


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


def alternatives(declared: str) -> tuple[SpecifierSet, ...] | None:
    """`declared` as the PEP 440 sets it is a union of; `None` if any part is unreadable.

    Poetry's `^`, `~`, `||`, a bare version and `x.*` are translated. An unreadable string leaves
    the run unblocked, since blocking on a string nobody parsed would be a guess, and is reported.
    """
    sets: list[SpecifierSet] = []
    for part in declared.split("||"):
        text = _OPERATOR_GAP.sub(r"\1", part.strip())
        terms = [_term(term) for term in _TERMS.split(text) if term] or ["*"]
        if None in terms:
            return None
        try:
            sets.append(SpecifierSet(",".join(term for term in terms if term and term != "*")))
        except InvalidSpecifier:
            return None
    return tuple(sets)


_OPERATOR_GAP: Final = re.compile(r"(\^|~=|~|===|==|!=|<=|>=|<|>)\s+")
_TERMS: Final = re.compile(r"[,\s]+")


def _term(term: str) -> str | None:
    """One Poetry or PEP 440 term as PEP 440, `""` for any version, `None` if unreadable."""
    if term == "*":
        return ""
    if term[0] in "^~" and not term.startswith("~="):
        return _caret_or_tilde(term)
    if term[0].isdigit():
        return f"=={term}"
    return term


def _caret_or_tilde(text: str) -> str | None:
    """Poetry's `^3.9` as `>=3.9,<4` (a Python major is never 0), `~3.9` as `>=3.9,<3.10`."""
    body = text[1:].strip()
    parts = body.split(".")
    if not body or not all(part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if text[0] == "^" or len(numbers) == 1:
        upper = f"{numbers[0] + 1}"
    else:
        upper = f"{numbers[0]}.{numbers[1] + 1}"
    return f">={body},<{upper}"


def lowest(declared: str | None) -> Version | None:
    """The lowest version `declared` admits, or `None` when it names no floor or cannot be read."""
    found = None if declared is None else alternatives(declared)
    if found is None:
        return None
    floors = [bounds(part)[0] for part in found]
    return None if None in floors else min(floor for floor in floors if floor is not None)


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
        spec=str(parsed.specifier) if parsed.url is None else None,
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


_INLINE_VERSION: Final = re.compile(r"""^\{.*?\bversion\s*=\s*(["'])(.*?)\1""")


def _inline_version(body: str, after: int) -> str | None:
    """The `version` of a one-line inline table (`{ version = "^3", extras = [...] }`), else `None`.

    Read, not edited: the table has no pin the rule could replace.
    """
    found = _INLINE_VERSION.match(body[after:].strip())
    return None if found is None else found.group(2)


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
                pin = _value_pin(body, column + cut + 1)
                spec = _inline_version(body, column + cut + 1) if pin is None else None
                yield replace(
                    declaration,
                    pin=pin,
                    spec=spec if pin is None else body[pin[0] : pin[1]],
                )
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
        try:
            text = node.evaluated_value
        except (SyntaxError, ValueError):
            # `"C:\Users"` is no string at all: Python refuses the escape, so it names nothing.
            continue
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
