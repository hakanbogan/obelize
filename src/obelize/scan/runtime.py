"""What the project declares about Python and the legacy pin, and whether that blocks the run.

A repository declaring support for a Python the new distribution does not install on, or a legacy
pin outside the pack's range, is blocked: it proposes nothing but is still reported. The Python
comes from the manifest, never the parser: libcst's native parser ignores
`PartialParserConfig(python_version=...)`. "Declares support for" is the test: `>=3.9` admits 3.9,
where pip installs an older, different API.
"""

from __future__ import annotations

import ast
import configparser
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Final

from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from obelize.models import BlockedReason, ScanSpec, terminal_unsafe
from obelize.scan import parse
from obelize.scan.manifests import Declaration, alternatives, lowest

# Each one is asked, not one comparison: `>=3.7,!=3.9.*` admits 3.8 but not 3.9. Each minor is asked
# at its last patch too, since `>=3.8.1` admits 3.8 only from its first patch on.
_MINORS: Final = ("2.7", *(f"3.{minor}" for minor in range(30)))
PYTHONS: Final[tuple[str, ...]] = tuple(
    version for minor in _MINORS for version in (minor, f"{minor}.999999")
)


@dataclass(frozen=True, slots=True)
class Declared:
    """One declared Python constraint."""

    path: str
    # Quoted verbatim: a version range, not source, so not redacted.
    declared: str


@dataclass(frozen=True, slots=True)
class Blocked:
    """Why a run proposes nothing: a repository status, not a per-file bail."""

    reason: BlockedReason
    # The distribution the declaration is about: the new one for a Python, the legacy one for a pin.
    package: str
    path: str
    # `None` when the legacy pin names no version.
    declared: str | None
    # The set a declaration has to stay inside, as a PEP 440 specifier.
    needed: str
    # The path that stops the newest release being taken for an unpinned legacy declaration.
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class Floor:
    """What the manifests say about Python, and the ones that could not say."""

    # The declaration that decided: the first that blocks, else the first read; `None` if none.
    declared: Declared | None
    blocked: Blocked | None
    # Unreadable manifests, so a floor nobody read differs from no floor.
    limitations: tuple[parse.Limitation, ...]


# What was lost, not the parser's words: `configparser` quotes the user's line back.
UNPARSED: Final[dict[str, str]] = {
    "pyproject.toml": "not TOML 1.0, so the Python it requires was not read",
    "setup.cfg": "not a setup.cfg setuptools can read, so the Python it requires was not read",
    "Pipfile": "not TOML 1.0, so the Python it requires was not read",
}
UNREAD: Final = "a Python requirement of a form obelize does not read, so it was not checked"


def detect(paths: tuple[str, ...], contents: parse.Contents, spec: ScanSpec) -> Floor:
    """The first declaration that admits a Python the new distribution rejects, and the manifests
    that could not say.

    The row is the first by depth then path, so the root `pyproject.toml` precedes a package's.
    """
    found: list[Declared] = []
    unparsed: list[parse.Limitation] = []
    for path in _ordered(paths):
        row = declaration(path, contents)
        if isinstance(row, parse.Limitation):
            unparsed.append(row)
        elif row is not None:
            found.append(row)
    blocking = next((row for row in found if _admits_unsupported(row.declared, spec)), None)
    blocked = None
    if blocking is not None:
        blocked = Blocked(
            reason="runtime_unsupported",
            package=spec.new_distribution,
            path=blocking.path,
            declared=blocking.declared,
            needed=spec.requires_python,
        )
    settled = blocking or (found[0] if found else None)
    return Floor(declared=settled, blocked=blocked, limitations=tuple(unparsed))


def legacy(
    found: Sequence[Declaration],
    spec: ScanSpec,
    used: bool,
    newest: str | None = None,
    contrary: str = "",
) -> Blocked | None:
    """The first legacy declaration that pins no version at or above the pack's floor.

    `used` is whether any source row is an edit candidate: a repository that never imports the
    legacy module is not blocked, by a pin below the floor or by one it does not declare. With
    `newest`, a declaration that installs it passes too (`installs`), unless `contrary` names the
    path that says another release is in use, which is then the block's evidence.
    """
    if spec.legacy_floor is None or not used:
        return None
    floor = Version(spec.legacy_floor)
    needed = f">={floor}"
    name = canonicalize_name(spec.legacy_distribution)
    rows = sorted(
        (row for row in found if row.name == name),
        key=lambda row: (row.path.count("/"), row.path.encode("utf-8"), row.line),
    )
    for row in rows:
        admitted = lowest(row.spec)
        if (admitted is None or admitted < floor) and not (
            newest and not contrary and installs(row, newest)
        ):
            return Blocked(
                "legacy_version_unsupported",
                spec.legacy_distribution,
                row.path,
                _shown(row.spec),
                needed,
                contrary,
            )
    if not rows:
        return Blocked("legacy_version_unsupported", spec.legacy_distribution, "", None, needed)
    return None


def installs(row: Declaration, newest: str) -> bool:
    """Whether a plain requirement installs `newest`: its pin span is the whole requirement, no
    marker may switch it off, and no pre-release is allowed to be picked instead."""
    if row.pin is None or row.marked or row.spec is None:
        return False
    found = alternatives(row.spec)
    return (
        found is not None
        and not any(part.prereleases for part in found)
        and any(part.contains(newest) for part in found)
    )


def inferred(found: Sequence[Declaration], spec: ScanSpec) -> bool:
    """Whether a legacy declaration passes `legacy` only because it installs the newest release."""
    if spec.legacy_floor is None or spec.legacy_newest is None:
        return False
    floor = Version(spec.legacy_floor)
    name = canonicalize_name(spec.legacy_distribution)
    return any(
        row.name == name
        and ((admitted := lowest(row.spec)) is None or admitted < floor)
        and installs(row, spec.legacy_newest)
        for row in found
    )


def _shown(declared: str | None) -> str | None:
    """The text a report may quote: one that reads as a version set, so nothing else is echoed."""
    readable = declared is not None and alternatives(declared) is not None
    return declared if readable and terminal_unsafe(declared or "") is None else None


def declaration(path: str, contents: parse.Contents) -> Declared | parse.Limitation | None:
    """One manifest's constraint: `None` if it declares none, a `Limitation` if it does not parse.

    Read through `contents`, so `max_file_bytes` and the path guard apply.
    """
    found = PurePosixPath(path).name
    reader = _READERS.get(found)
    if reader is None:
        return None
    data, _refused = contents(path)
    if data is None:
        return None
    try:
        declared = reader(data)
    except ValueError:
        return parse.Limitation(path=path, code="input_does_not_parse", detail=UNPARSED[found])
    if declared is None:
        return None
    if alternatives(declared) is None:
        return parse.Limitation(path=path, code="input_does_not_parse", detail=UNREAD)
    return Declared(path=path, declared=declared)


def _admits_unsupported(declared: str, spec: ScanSpec) -> bool:
    """Whether the declaration admits an interpreter the new distribution does not install on.

    Besides the grid, a release the declaration names itself (`==3.9.18`): no grid has every patch.
    """
    found = alternatives(declared)
    if found is None:
        return False
    supported = SpecifierSet(spec.requires_python)
    named = tuple(
        item.version
        for part in found
        for item in part
        if item.operator == "==" and not item.version.endswith("*")
    )
    return any(
        part.contains(version) and not supported.contains(version)
        for part in found
        for version in (*PYTHONS, *named)
    )


def _ordered(paths: tuple[str, ...]) -> list[str]:
    """Shallowest first, then by path bytes."""
    return sorted(paths, key=lambda path: (path.count("/"), path.encode("utf-8")))


def _from_toml(data: bytes) -> str | None:
    """`[project] requires-python`, then Poetry's key; `ValueError` unless UTF-8 TOML.

    Both decode errors are `ValueError`s. TOML 1.1 reads from Python 3.15 on, and before that it
    fails like any other syntax error.
    """
    document = tomllib.loads(data.decode("utf-8"))
    project = document.get("project")
    if isinstance(project, dict) and isinstance(value := project.get("requires-python"), str):
        return value
    section: Any = document
    for step in ("tool", "poetry", "dependencies", "python"):
        section = section.get(step) if isinstance(section, dict) else None
    return section if isinstance(section, str) else None


def _from_cfg(data: bytes) -> str | None:
    """`[options] python_requires`, via setuptools' parser; `ValueError` if not UTF-8 INI."""
    parser = configparser.ConfigParser()
    try:
        parser.read_string(data.decode("utf-8"))
    except configparser.Error as error:
        raise ValueError("not INI") from error
    value = parser.get("options", "python_requires", fallback=None)
    return value.strip() if value else None


def _from_pipfile(data: bytes) -> str | None:
    """`[requires]`: `python_full_version` as that release, `python_version` as every patch of that
    minor, which is the interpreter pipenv builds the environment from; `ValueError` unless UTF-8
    TOML."""
    requires = tomllib.loads(data.decode("utf-8")).get("requires")
    if not isinstance(requires, dict):
        return None
    if isinstance(full := requires.get("python_full_version"), str):
        return f"=={full}"
    version = requires.get("python_version")
    return f"=={version}.*" if isinstance(version, str) else None


def _from_setup_py(data: bytes) -> str | None:
    """The first `python_requires=` given as a string literal; one built from a variable would be
    a guess. A file that does not parse declares nothing: the code pass reports it."""
    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    found = [
        (keyword.lineno, keyword.col_offset, keyword.value.value)
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        for keyword in call.keywords
        if keyword.arg == "python_requires"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    ]
    return min(found)[2] if found else None


# Keyed by name, not `manifests.layout`: `pyproject.toml` and a `Pipfile` are both TOML, and each
# keeps its Python elsewhere.
_READERS: Final[dict[str, Callable[[bytes], str | None]]] = {
    "pyproject.toml": _from_toml,
    "setup.cfg": _from_cfg,
    "Pipfile": _from_pipfile,
    "setup.py": _from_setup_py,
}

__all__ = [
    "PYTHONS",
    "UNPARSED",
    "UNREAD",
    "Blocked",
    "Declared",
    "Floor",
    "alternatives",
    "declaration",
    "detect",
    "inferred",
    "installs",
    "legacy",
]
