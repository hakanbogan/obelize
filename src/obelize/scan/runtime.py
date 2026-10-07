"""What the project declares about Python and the legacy pin, and whether that blocks the run.

A repository declaring support for a Python the new distribution does not install on, or a legacy
pin outside the pack's range, is blocked: it proposes nothing but is still reported. The Python
comes from the manifest, never the parser: libcst's native parser ignores
`PartialParserConfig(python_version=...)`. "Declares support for" is the test: `>=3.9` admits 3.9,
where pip installs an older, different API.
"""

from __future__ import annotations

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


def legacy(found: Sequence[Declaration], spec: ScanSpec, used: bool) -> Blocked | None:
    """The first legacy declaration that pins no version at or above the pack's floor.

    `used` is whether any source row is an edit candidate: a repository that never imports the
    legacy module is not blocked by a pin it does not declare.
    """
    if spec.legacy_floor is None:
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
        if admitted is None or admitted < floor:
            return Blocked(
                "legacy_version_unsupported",
                spec.legacy_distribution,
                row.path,
                _shown(row.spec),
                needed,
            )
    if not rows and used:
        return Blocked("legacy_version_unsupported", spec.legacy_distribution, "", None, needed)
    return None


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
    """Whether the declaration admits an interpreter the new distribution does not install on."""
    found = alternatives(declared)
    if found is None:
        return False
    supported = SpecifierSet(spec.requires_python)
    return any(
        part.contains(version) and not supported.contains(version)
        for part in found
        for version in PYTHONS
    )


def _ordered(paths: tuple[str, ...]) -> list[str]:
    """Shallowest first, then by path bytes."""
    return sorted(paths, key=lambda path: (path.count("/"), path.encode("utf-8")))


def _from_toml(data: bytes) -> str | None:
    """`[project] requires-python`, then Poetry's key; `ValueError` unless UTF-8 TOML 1.0.

    Both decode errors are `ValueError`s, and every supported `tomllib` refuses TOML 1.1 alike.
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


# `setup.py` is absent on purpose: a `python_requires=` built from a variable would be a guess.
# Keyed by name, not `manifests.layout`: a `Pipfile` is TOML too, but its `[requires]` is unread.
_READERS: Final[dict[str, Callable[[bytes], str | None]]] = {
    "pyproject.toml": _from_toml,
    "setup.cfg": _from_cfg,
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
    "legacy",
]
