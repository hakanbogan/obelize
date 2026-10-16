"""Read dependency manifests and grade the pin edits on them.

Names match by PEP 503 `canonicalize_name`, never substring. Files are read as lines, never
round-tripped (that would reformat them), so the recorded address is the one the edit uses.
"""

from __future__ import annotations

import ast
import fnmatch
import re
from dataclasses import astuple, dataclass, replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, Literal

import libcst as cst
from libcst.metadata import (
    Assignment,
    MetadataWrapper,
    ParentNodeProvider,
    PositionProvider,
    ScopeProvider,
)
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

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
    from collections.abc import Iterable, Iterator, Mapping, Sequence


# Every bail raised here, unranked: no two can fire on the same row.
BAILS: frozenset[BailCode] = frozenset(
    {"manifest_code_mismatch", REPO_ATOMICITY_BAIL, "transitive_dependency_in_use"}
)

# A pin the rule cannot write (extras, a URL). The rule raises it, and the corpus grades it there;
# here only a pack whose one distribution holds both APIs does, since its files wait on the pin.
SHAPE_BAIL: Final[BailCode] = "manifest_pin_shape_unsupported"

# Keeps a legacy pin for a module only it installs; asked once nothing imports the legacy one.
TRANSITIVE_BAIL: Final[BailCode] = "transitive_dependency_in_use"

# The fields of a statement, handler or `case` that hold statements.
_BODIES: Final = ("body", "orelse", "finalbody", "handlers", "cases")

# Only `setup_py` is Python. `unwritten` files are read for their declarations, which carry no pin.
Layout = Literal["requirements", "unwritten", "toml", "cfg", "setup_py"]

# Exact basenames. No lockfiles, deliberately: a line edit would break their hashes.
NAMES: Final[dict[str, Layout]] = {
    "Pipfile": "toml",
    "pyproject.toml": "toml",
    "setup.cfg": "cfg",
    "setup.py": "setup_py",
}

REQUIREMENTS_GLOB: Final = "*requirement*.txt"

# Read, never written: a constraints file and a pip-tools input. The compiled file beside an input
# is what installs, so an edit there alone would be undone by the next compile.
_CONSTRAINTS: Final = "*constraints*.txt"
UNWRITTEN_GLOBS: Final = (_CONSTRAINTS, "*requirements*.in")

# Layouts pip reads: a line may be an option, and a comment needs a blank before its `#`.
PIP: Final[frozenset[Layout]] = frozenset({"requirements", "unwritten"})

# Files nothing here reads that can still decide which release a requirement installs: a lock, the
# installer's own settings. Python-free `*.lock` files are not among them.
LOCKS: Final[frozenset[str]] = frozenset(
    {
        "Pipfile.lock",
        "conda-lock.yml",
        "environment.yaml",
        "environment.yml",
        "pdm.lock",
        "pip.conf",
        "pixi.lock",
        "poetry.lock",
        "pylock.toml",
        "uv.lock",
        "uv.toml",
    }
)
LOCK_GLOBS: Final = ("pylock.*.toml", "requirements*.lock")

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

# How pip reads a requirements line: a `#` starts a comment only at the start or after a blank (so
# a `#egg=` fragment is part of the line), and a token that starts with `-` begins the options.
PIP_COMMENT: Final = re.compile(r"(?:^|\s)#.*")
_PIP_OPTION: Final = re.compile(r"\s-")
_EDITABLE: Final = re.compile(r"(?:-e|--editable)(?:\s+|=)")
# The name of a requirement PEP 508 refuses: an `#egg=` fragment, or an archive's file name.
_EGG: Final = re.compile(r"[#&]egg=(?P<name>[A-Za-z0-9][\w.-]*)")
_ARCHIVE: Final = re.compile(
    r"(?P<name>[A-Za-z0-9](?:[\w.]|-(?!\d))*)-\d.*\.(?:whl|tar\.gz|tgz|zip)$"
)
# The name a line starts with when PEP 508 refuses the rest (`PyPDF2~=1`, `PyPDF2==1.*.*`).
_LEADING: Final = re.compile(
    r"\s*(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?=[\s\[(;<>=!~@,]|$)"
)


@dataclass(frozen=True, slots=True)
class Declaration:
    """One declared dependency: canonical `name`; `raw` as written, from `column` to `end`.

    `pin` spans the version, or is `None` for extras, a URL, a hash, an editable requirement, a file
    no rule writes or a non-string value a rewrite cannot carry; the rule refuses such a row and the
    scan still reports it. `spec` is the version as declared (a PEP 508 set, or Poetry's or
    Pipenv's string), `None` when it cannot be read.
    """

    path: str
    line: int
    column: int
    name: str
    raw: str
    end: int
    pin: tuple[int, int] | None
    spec: str | None
    # An environment marker follows the version: the pin may not apply on every system.
    marked: bool = False


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
    # Some file uses a name only the new API defines (`ScanSpec.new_names`).
    modern: bool = False


def layout(path: str) -> Layout | None:
    """How to read `path`, or `None` when it is not a manifest at all."""
    name = PurePosixPath(path).name
    if name in NAMES:
        return NAMES[name]
    # `fnmatchcase`: `fnmatch` folds case on Windows only, and the answer must not vary by OS.
    if any(fnmatch.fnmatchcase(name, glob) for glob in UNWRITTEN_GLOBS):
        return "unwritten"
    if not fnmatch.fnmatchcase(name, "*.txt"):
        return None
    if fnmatch.fnmatchcase(name, REQUIREMENTS_GLOB):
        return "requirements"
    parent = PurePosixPath(path).parent.name
    return "requirements" if parent == REQUIREMENTS_DIRECTORY else None


def is_manifest(path: str) -> bool:
    return layout(path) is not None


def is_lock(path: str) -> bool:
    """Whether `path` can pin or constrain a release without being a manifest this reads."""
    name = PurePosixPath(path).name
    return name in LOCKS or (
        layout(path) is None and any(fnmatch.fnmatchcase(name, glob) for glob in LOCK_GLOBS)
    )


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
    readers = {
        "requirements": _from_requirements,
        "unwritten": _from_unwritten,
        "toml": _from_toml,
        "cfg": _from_cfg,
    }
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
    modern: bool = False,
) -> Migration:
    """The pin-edit conditions from the per-file plans, plus what no plan carries.

    A file migrated if any row is eligible; it blocks if a non-eligible row still loads the
    distribution (`IMPORTING` or a mock target). `unanalysed` files block like an import. Where
    `paired` (see `coupled`) no import marks the old API, so any withheld row blocks. `modern` is
    whether any file uses a name only the new API defines (`uses_new_names`).
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
        modern=modern,
    )


def provided(path: str, data: bytes, spec: ScanSpec) -> tuple[tuple[str, str], ...]:
    """(path, distribution) per real import, not mention, of a module only the legacy one installed.

    An unparsable file yields nothing; the scan reports it elsewhere.
    """
    if not any(row.module.rpartition(".")[2].encode() in data for row in spec.transitive_modules):
        return ()
    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return ()
    imported: set[str] = set()
    # Only a statement holds one, so the walk skips expressions, most of a tree's nodes.
    pending: list[ast.AST] = [tree]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and not node.level:
                imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        else:
            for field in _BODIES:
                pending.extend(getattr(node, field, ()))
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


def uses_new_names(data: bytes, spec: ScanSpec) -> bool:
    """Whether a file uses a name only the new API defines, as written or through an alias.

    Read from the imports and the attributes of what they bind, so a local variable of the same name
    is not one. An unparsable file yields nothing; the scan reports it elsewhere.
    """
    if not any(name.rpartition(".")[2].encode() in data for name in spec.new_names):
        return False
    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    bound: dict[str, str] = {}
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.partition(".")[0]
                bound[alias.asname or top] = alias.name if alias.asname else top
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
                used.add(f"{node.module}.{alias.name}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            parts = [node.attr]
            value = node.value
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if isinstance(value, ast.Name) and value.id in bound:
                used.add(".".join((bound[value.id], *reversed(parts))))
    return any(name == new or name.startswith(f"{new}.") for name in used for new in spec.new_names)


def declares(found: Iterable[Declaration], spec: ScanSpec) -> bool:
    """Whether a manifest declares the pack's legacy distribution."""
    legacy = canonicalize_name(spec.legacy_distribution)
    return any(declaration.name == legacy for declaration in found)


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
    """Grade every declaration against the pin-edit rule and the state of the code.

    A file imports a module only the legacy distribution installed with a declaration of its
    distribution in the manifests of its own app: its directory, or one above it, up to the root. A
    constraints file does not declare: it bounds a version and installs nothing.
    """
    legacy = canonicalize_name(spec.legacy_distribution)
    new = canonicalize_name(spec.new_distribution)
    declares: dict[str, set[str]] = {}
    owners: dict[str, set[PurePosixPath]] = {}
    for declaration in found:
        declares.setdefault(declaration.path, set()).add(declaration.name)
        if not fnmatch.fnmatchcase(PurePosixPath(declaration.path).name, _CONSTRAINTS):
            owners.setdefault(declaration.name, set()).add(_owner(declaration.path))
    needed = tuple(
        sorted(
            {
                path
                for path, distribution in migration.transitive
                if not any(
                    parent in owners.get(canonicalize_name(distribution), ())
                    for parent in PurePosixPath(path).parents
                )
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


def _owner(path: str) -> PurePosixPath:
    """The directory a manifest declares for: its own, or the parent of a `requirements/` one."""
    parent = PurePosixPath(path).parent
    return parent.parent if parent.name == REQUIREMENTS_DIRECTORY else parent


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
        code = (
            REPO_ATOMICITY_BAIL
            if migration.blocking
            else None
            if needed
            or migration.excluded
            or (coupled(spec) and not (migration.modern and _legacy_only(declaration, spec)))
            else "manifest_code_mismatch"
        )
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


def _legacy_only(declaration: Declaration, spec: ScanSpec) -> bool:
    """Whether a declaration admits some release of the legacy range and none above it, so code
    that uses a name only the new API defines cannot run on what it installs. One nobody can read
    is not judged."""
    found = None if declaration.spec is None else alternatives(declaration.spec)
    legacy = SpecifierSet(spec.legacy_range)
    ceiling = bounds(legacy)[1]
    return (
        found is not None
        and ceiling is not None
        and meets(found, legacy)
        and not meets(found, SpecifierSet(f">={ceiling}"))
    )


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
    """Poetry's `^1.2` as `>=1.2,<2`, `^0.27` as `>=0.27,<0.28`, `~3.9` as `>=3.9,<3.10`.

    A caret ends at the first non-zero part (the last one when all are zero), a tilde at the minor.
    """
    body = text[1:].strip()
    parts = body.split(".")
    if not body or not all(part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if text[0] == "^":
        end = next((at for at, number in enumerate(numbers) if number), len(numbers) - 1)
    else:
        end = min(1, len(numbers) - 1)
    upper = ".".join(str(number) for number in (*numbers[:end], numbers[end] + 1))
    return f">={body},<{upper}"


def lowest(declared: str | None) -> Version | None:
    """The lowest version `declared` admits, or `None` when it names no floor, cannot be read, or
    names a local build (`==3.0.1+corp`): that is not the release the floor was measured on."""
    found = None if declared is None else alternatives(declared)
    if found is None:
        return None
    floors = [bounds(part)[0] for part in found]
    if None in floors or any(floor is not None and floor.local for floor in floors):
        return None
    return min(floor for floor in floors if floor is not None)


def meets(found: Iterable[SpecifierSet], target: SpecifierSet) -> bool:
    """Whether some release is in `target` and in one of `found`.

    The two sets meet where some version is in both. One is found at a version either names, just
    above one, the release after one (where `!=6.19.*` ends) or at 0, since a range of PEP 440
    specifiers starts at one of them.
    """
    for part in found:
        both = part & target
        try:
            named = {Version(item.version.removesuffix(".*")) for item in both}
        except InvalidVersion:  # `===` takes any string
            return True
        probes = {
            Version("0"),
            *named,
            *(Version(f"{version.base_version}.0.1") for version in named),
            *map(_after, named),
        }
        if any(both.contains(version, prereleases=True) for version in probes):
            return True
    return False


def _after(version: Version) -> Version:
    """The release after `version` at its own depth: where `!=6.19.*` ends, at 6.20."""
    *head, last = version.release
    return Version(".".join(map(str, (*head, last + 1))))


def _requirement(path: str, line: int, column: int, text: str) -> Declaration | None:
    """A requirement string, or the name it starts with where PEP 508 refuses the rest: a version
    nobody can read is a row the gate cannot judge, not one it may skip."""
    return _declare(path, line, column, text) or _unreadable(path, line, column, text)


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
        marked=marker >= 0,
    )


def _span(text: str) -> tuple[str, int]:
    """`text` without its surrounding blanks, and the column it starts at."""
    body = text.rstrip(_BLANK + "\r\n")
    column = len(body) - len(body.lstrip(_BLANK))
    return body[column:], column


def uncommented(text: str) -> str:
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


def _joined(lines: list[str]) -> Iterator[tuple[int, str, bool]]:
    """pip's logical lines: the number of the first, its text, and whether it spans several.

    A line ending in a backslash goes on with the next, but a comment line never does.
    """
    first = 0
    parts: list[str] = []
    for number, line in enumerate(lines, 1):
        text = line.rstrip("\r")
        goes_on = text.endswith("\\") and not text.lstrip(_BLANK).startswith("#")
        if not parts:
            first = number
        parts.append(text[:-1] if goes_on else text)
        if not goes_on:
            yield first, "".join(parts), len(parts) > 1
            parts = []
    if parts:
        yield first, "".join(parts), True


def _archive(path: str, line: int, column: int, text: str) -> Declaration | None:
    """A requirement pip takes and PEP 508 does not, known by its name only: the `#egg=` of a VCS
    URL, or the file name of an archive; no version is read from either."""
    head = re.split("[#?]", text, maxsplit=1)[0]
    found = _EGG.search(text) or _ARCHIVE.match(head, head.rfind("/") + 1)
    return None if found is None else _named(path, line, column, found)


def _unreadable(path: str, line: int, column: int, text: str) -> Declaration | None:
    """A requirement PEP 508 refuses, known by the name it starts with; no version is read."""
    found = _LEADING.match(text)
    return None if found is None else _named(path, line, column, found)


def _named(path: str, line: int, column: int, found: re.Match[str]) -> Declaration:
    start, end = found.span("name")
    return Declaration(
        path=path,
        line=line,
        column=column + start,
        name=canonicalize_name(found["name"]),
        raw=found["name"],
        end=column + end,
        pin=None,
        spec=None,
    )


def _from_requirements(path: str, lines: list[str]) -> Iterator[Declaration]:
    """One requirement per logical line, as pip reads it.

    The options after a requirement (`--hash`) are cut before it is read. A requirement that
    carries a hash, spans lines or is editable gets no pin: a hash belongs to its release, and a
    copy of a continued line would split it.
    """
    for number, text, joined in _joined(lines):
        body, column = _span(PIP_COMMENT.sub("", text))
        if not body:
            continue
        editable = _EDITABLE.match(body)
        if editable:
            body, column = body[editable.end() :], column + editable.end()
        elif body.startswith("-"):
            continue
        cut = _PIP_OPTION.search(body)
        written = body[: cut.start()] if cut else body
        declaration = (
            _declare(path, number, column, written)
            or _archive(path, number, column, written)
            or _unreadable(path, number, column, written)
        )
        if declaration is None:
            continue
        if editable or joined or "--hash" in body[len(written) :]:
            declaration = replace(
                declaration, pin=None, spec=None if editable else declaration.spec
            )
        yield declaration


def _from_unwritten(path: str, lines: list[str]) -> Iterator[Declaration]:
    """A constraints file or a pip-tools input, whose declarations are read and never edited.

    A bare name constrains nothing, and the compiled file beside it names the release, so it is
    not a declaration.
    """
    for declaration in _from_requirements(path, lines):
        if declaration.spec != "":
            yield replace(declaration, pin=None)


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
    """Requirement arrays: PEP 621/735, uv's dev group, every PDM group and a Hatch environment's;
    not `[build-system] requires`, which installs never read."""
    if table == ("project",):
        return key == "dependencies"
    if table == ("tool", "uv"):
        return key == "dev-dependencies"
    if len(table) == 4 and table[:3] == ("tool", "hatch", "envs"):
        return key in {"dependencies", "extra-dependencies"}
    return table in {
        ("dependency-groups",),
        ("project", "optional-dependencies"),
        ("tool", "pdm", "dev-dependencies"),
    }


def _value_pin(body: str, after: int) -> tuple[int, int] | None:
    """The span inside a TOML value that is exactly one quoted string, or an inline table holding
    nothing but a quoted `version`; else `None`.

    Also refuses an unclosed quote (invalid TOML); an inner quote (triple-quoted, escaped) is fine.
    """
    rest = body[after:]
    value = rest.strip()
    start = after + len(rest) - len(rest.lstrip())
    only = _ONLY_VERSION.fullmatch(value)
    if only:
        return (start + only.start("version"), start + only.end("version"))
    quote = value[:1]
    if len(value) < 2 or quote not in "\"'" or value[-1] != quote:
        return None
    return (start + 1, start + len(value) - 1)


# Any other key beside the version (extras, a marker, a source) would be carried to a distribution
# that may not have it, so such a table is no pin.
_ONLY_VERSION: Final = re.compile(r"""\{\s*version\s*=\s*(["'])(?P<version>[^"']*)\1\s*,?\s*\}""")
_INLINE_VERSION: Final = re.compile(r"""^\{.*?\bversion\s*=\s*(["'])(.*?)\1""")


def _inline_version(body: str, after: int) -> str | None:
    """The `version` of a one-line inline table (`{ version = "^3", extras = [...] }`), else `None`.

    Read, not edited: with other keys beside it the table has no pin the rule could replace.
    """
    found = _INLINE_VERSION.match(body[after:].strip())
    return None if found is None else found.group(2)


def _version_below(lines: list[str], start: int) -> str | None:
    """The `version` string in the table whose body starts at `lines[start]`, else `None`."""
    for line in lines[start:]:
        body = uncommented(line)
        text, column = _span(body)
        if text.startswith("["):
            break
        key, equals, _ = text.partition("=")
        if equals and key.strip() == "version":
            pin = _value_pin(body, column + len(key) + 1)
            return None if pin is None else body[pin[0] : pin[1]]
    return None


def _headed(
    path: str, number: int, column: int, name: str, lines: list[str]
) -> Iterator[Declaration]:
    """A dependency given as its own table, `[tool.poetry.dependencies.name]`.

    No pin: the name is on the header and the version on another line, and an edit has one line to
    a declaration, so the rule refuses the row and the repository is held.
    """
    declaration = _declare(path, number, column, name)
    if declaration is not None:
        yield replace(declaration, pin=None, spec=_version_below(lines, number))


def _from_toml(path: str, lines: list[str]) -> Iterator[Declaration]:
    """`pyproject.toml` and `Pipfile`, read as lines.

    Under a dependency table the key is the distribution; in a dependency array each string is a
    requirement. An array closes by `[`/`]` depth, counted after comments are stripped.
    """
    table: tuple[str, ...] = ()
    depth = 0
    for number, line in enumerate(lines, 1):
        body = uncommented(line)
        if depth > 0:
            yield from _array(path, number, body, 0)
            depth += body.count("[") - body.count("]")
            continue
        text, column = _span(body)
        if text.startswith("["):
            table = _table(text)
            if _is_dependency_table(table[:-1]):
                yield from _headed(path, number, column + text.rfind(table[-1]), table[-1], lines)
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
        declaration = _requirement(path, number, column, text)
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
                declaration = _requirement(path, number, column, text)
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
            declaration = _requirement(path, number, column + cut + 1 + offset, value)
            if declaration is not None:
                yield declaration


class _Requirements(cst.CSTVisitor):
    """Literals under a `setup()` requirement keyword, except dict keys (an extra's name), and the
    names standing there for a whole list."""

    def __init__(self, depth: int = 0) -> None:
        self.strings: list[cst.SimpleString] = []
        self.names: list[cst.Name] = []
        self._depth = depth
        self._keys = 0

    def visit_Arg(self, node: cst.Arg) -> None:
        if self.wanted(node):
            self._depth += 1
            self._name(node.value)

    def leave_Arg(self, node: cst.Arg) -> None:
        if self.wanted(node):
            self._depth -= 1

    def visit_Element(self, node: cst.Element) -> None:
        self._name(node.value)

    def visit_DictElement(self, node: cst.DictElement) -> None:
        self._name(node.value)

    def visit_DictElement_key(self, node: cst.DictElement) -> None:
        self._keys += 1

    def leave_DictElement_key(self, node: cst.DictElement) -> None:
        self._keys -= 1

    def visit_SimpleString(self, node: cst.SimpleString) -> None:
        if self._depth and not self._keys:
            self.strings.append(node)

    def _name(self, value: cst.BaseExpression) -> None:
        if self._depth and not self._keys and isinstance(value, cst.Name):
            self.names.append(value)

    @staticmethod
    def wanted(node: cst.Arg) -> bool:
        return node.keyword is not None and node.keyword.value in SETUP_KEYWORDS


_BUILT: Final = (
    cst.BinaryOperation,
    cst.ConcatenatedString,
    cst.Call,
    cst.Subscript,
    cst.FormattedString,
)
_CONTAINERS: Final = (cst.List, cst.Tuple, cst.Set, cst.DictElement)


def _whole(node: cst.CSTNode, parents: Mapping[cst.CSTNode, cst.CSTNode]) -> bool:
    """Whether the literal is a requirement by itself, not built around by an operator, a call, a
    subscript or a string concatenation (`"PyPDF2" + V`, `"PyPDF2" ">=3"`)."""
    while not isinstance(node := parents[node], _CONTAINERS):
        if isinstance(node, _BUILT):
            return False
        if isinstance(node, cst.Arg) and _Requirements.wanted(node):
            break
    return True


def _stood_for(
    names: Sequence[cst.Name], wrapper: MetadataWrapper, parents: Mapping[cst.CSTNode, cst.CSTNode]
) -> list[cst.SimpleString]:
    """The strings of the list, tuple or dict literal each name stands for: the one assignment that
    binds it, and those of the names inside it in turn. A name bound twice, by an import, a
    parameter or anything but `NAME = [...]` is not followed."""
    if not names:
        return []
    scopes = wrapper.resolve(ScopeProvider)
    pending = list(names)
    followed: set[cst.CSTNode] = set()
    strings: list[cst.SimpleString] = []
    while pending:
        name = pending.pop()
        scope = scopes[name]
        if scope is None:  # pragma: no cover - every node is in some scope
            continue
        bound = scope[name.value]
        if len(bound) != 1:
            continue
        (only,) = bound
        target = parents[only.node] if isinstance(only, Assignment) else None
        assign = parents[target] if isinstance(target, cst.AssignTarget) else None
        if (
            isinstance(assign, cst.Assign)
            and len(assign.targets) == 1
            and isinstance(assign.value, (cst.List, cst.Tuple, cst.Dict))
            and assign.value not in followed
        ):
            followed.add(assign.value)
            inside = _Requirements(depth=1)
            assign.value.visit(inside)
            strings.extend(inside.strings)
            pending.extend(inside.names)
    return strings


def _from_setup_py(path: str, data: bytes) -> Iterator[Declaration]:
    """`setup.py`: only literals under requirement keywords declare, or in the one list literal a
    name there stands for; unparsable yields nothing."""
    module = parse.gates(path, data).module
    if module is None:
        return
    # Without `unsafe_skip_copy` the wrapper deep-copies, and collected nodes lack positions.
    wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
    collector = _Requirements()
    try:
        positions = wrapper.resolve(PositionProvider)
        module.visit(collector)
        parents = (
            wrapper.resolve(ParentNodeProvider) if collector.strings or collector.names else {}
        )
        strings = [*collector.strings, *_stood_for(collector.names, wrapper, parents)]
    except (RecursionError, MemoryError):  # parsed, but too deep to walk: declares nothing
        return
    lines = data.decode("utf-8", "surrogateescape").split("\n")
    for node in sorted(strings, key=lambda node: astuple(positions[node].start)):
        text = node.evaluated_value
        if not isinstance(text, str):
            continue
        at = positions[node].start
        declaration = _requirement(
            path, at.line, at.column + len(node.prefix) + len(node.quote), text
        )
        if declaration is None:
            continue
        # Spans are source columns only when the literal's bytes are its value (an escape, and a
        # multi-line literal is an escaped newline, breaks that) and libcst's line is the edit's:
        # it breaks a line at a lone CR and drops a BOM. The row stays; the pin goes, and also when
        # other code builds the requirement around the literal.
        line = "".join(lines[at.line - 1 : at.line])
        opening = node.prefix + node.quote + node.raw_value.split("\n")[0]
        faithful = node.raw_value == text and line.startswith(opening, at.column)
        yield declaration if faithful and _whole(node, parents) else replace(declaration, pin=None)


__all__ = [
    "BAILS",
    "IMPORTING",
    "KIND",
    "LOCKS",
    "LOCK_GLOBS",
    "NAMES",
    "PIP",
    "PIP_COMMENT",
    "REASON",
    "REQUIREMENTS_DIRECTORY",
    "REQUIREMENTS_GLOB",
    "SETUP_KEYWORDS",
    "TRANSITIVE_BAIL",
    "UNWRITTEN_GLOBS",
    "Declaration",
    "Layout",
    "Migration",
    "Reading",
    "declarations",
    "is_lock",
    "is_manifest",
    "layout",
    "plan",
    "prefiltered",
    "provided",
    "read",
    "survey",
    "uncommented",
]
