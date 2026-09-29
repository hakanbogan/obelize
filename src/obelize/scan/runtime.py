"""The project's declared Python floor, and whether it blocks the run.

`google-genai` needs Python 3.10+, so a repository declaring older support is blocked: it
proposes nothing but is still reported. The floor comes from the manifest, never the parser:
libcst's native parser ignores `PartialParserConfig(python_version=...)`.
"Declares support for" is the test: `>=3.9` admits 3.9, where pip installs an older, different API.
"""

from __future__ import annotations

import configparser
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from obelize.models import BlockedReason, Config
from obelize.scan import parse

# `google-genai` 2.x does not install below it: a repository status, not a per-file bail.
FLOOR: Final = "3.10"

# Each one is asked, not one comparison: `>=3.7,!=3.9.*` admits 3.8 but not 3.9.
BELOW_FLOOR: Final[tuple[str, ...]] = (
    "2.7",
    *(f"3.{minor}" for minor in range(10)),
)

BLOCKED: Final[BlockedReason] = "runtime_unsupported"


@dataclass(frozen=True, slots=True)
class Declared:
    """One declared Python constraint, and what it means for this migration."""

    path: str
    # Quoted verbatim: a version range, not source, so not redacted.
    declared: str
    # Admits an interpreter below `FLOOR`.
    blocked: bool


@dataclass(frozen=True, slots=True)
class Floor:
    """What the manifests say about Python, and the ones that could not say."""

    # The settling declaration; `None` when none was read.
    declared: Declared | None
    # Unreadable manifests, so a floor nobody read differs from no floor.
    limitations: tuple[parse.Limitation, ...]


# What was lost, not the parser's words: `configparser` quotes the user's line back.
UNPARSED: Final[dict[str, str]] = {
    "pyproject.toml": "not TOML 1.0, so the Python it requires was not read",
    "setup.cfg": "not a setup.cfg setuptools can read, so the Python it requires was not read",
}


def detect(root: Path, paths: tuple[str, ...], config: Config) -> Floor:
    """The settling declaration, and the manifests that could not say.

    Blocked when any manifest declares below `FLOOR`. The row is the first blocking declaration,
    else the first, by depth then path, so the root `pyproject.toml` precedes a package's.
    """
    found: list[Declared] = []
    unparsed: list[parse.Limitation] = []
    for path in _ordered(paths):
        row = declaration(root, path, config)
        if isinstance(row, parse.Limitation):
            unparsed.append(row)
        elif row is not None:
            found.append(row)
    blocking = [row for row in found if row.blocked]
    settled = blocking[0] if blocking else (found[0] if found else None)
    return Floor(declared=settled, limitations=tuple(unparsed))


def declaration(root: Path, path: str, config: Config) -> Declared | parse.Limitation | None:
    """One manifest's constraint: `None` if it declares none, a `Limitation` if it does not parse.

    Read through `parse.contents`, so `max_file_bytes` and the path guard apply.
    """
    found = PurePosixPath(path).name
    reader = _READERS.get(found)
    if reader is None:
        return None
    data, _refused = parse.contents(root, path, config)
    if data is None:
        return None
    try:
        declared = reader(data)
    except ValueError:
        return parse.Limitation(path=path, code="input_does_not_parse", detail=UNPARSED[found])
    if declared is None:
        return None
    return Declared(path=path, declared=declared, blocked=_admits_legacy(declared))


def specifier(declared: str) -> SpecifierSet | None:
    """`declared` as a PEP 440 set, translating Poetry's `^`/`~`; `None` if unreadable.

    `None` leaves the run unblocked: blocking on a string nobody parsed would be a guess.
    """
    text = declared.strip()
    if not text or text == "*":
        # Poetry's "any version": still a declaration, and it admits 3.9.
        return SpecifierSet("")
    if text[0] in "^~" and (translated := _caret_or_tilde(text)) is not None:
        return translated
    try:
        return SpecifierSet(text)
    except InvalidSpecifier:
        return None


def _admits_legacy(declared: str) -> bool:
    """Whether the declaration admits any interpreter below the floor."""
    parsed = specifier(declared)
    if parsed is None:
        return False
    return any(parsed.contains(version) for version in BELOW_FLOOR)


def _caret_or_tilde(text: str) -> SpecifierSet | None:
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
    return SpecifierSet(f">={body},<{upper}")


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
    "BELOW_FLOOR",
    "BLOCKED",
    "FLOOR",
    "UNPARSED",
    "Declared",
    "Floor",
    "declaration",
    "detect",
    "specifier",
]
