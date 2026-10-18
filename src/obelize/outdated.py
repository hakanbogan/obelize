"""`obelize outdated`: what the package index says of each dependency a repository declares.

For every distribution the manifests name: the release the declaration starts at, the newest one,
how far apart they are, whether the library marks itself inactive, whether the release in use was
withdrawn or has an advisory, and what obelize knows to migrate it with (a bundled pack, or two
releases to compare). Nothing is installed and nothing is written.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from obelize import index
from obelize.models import bounds
from obelize.models.fields import _Frozen
from obelize.net import NetworkError

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from obelize.net import Fetcher
    from obelize.packs.loader import LoadedPack
    from obelize.scan.manifests import Declaration

Gap = Literal["none", "patch", "minor", "major", "unknown"]
Flag = Literal["inactive", "yanked", "advisory"]
Knowledge = Literal["bundled", "synthesizable", "none"]
# How many distributions are asked about at once.
WORKERS: Final = 8
INACTIVE: Final = "Development Status :: 7 - Inactive"
NOT_FOUND: Final = "not on the index"
# The table names this many advisories of a release; `--json` has them all.
ADVISORIES_SHOWN: Final = 2


class Row(_Frozen):
    distribution: str
    declared: str | None
    current: str | None
    newest: str | None
    gap: Gap
    flags: tuple[Flag, ...]
    advisories: tuple[str, ...]
    knowledge: Knowledge
    pack: str | None
    paths: tuple[str, ...]
    error: str | None


class Document(_Frozen):
    index: str
    rows: tuple[Row, ...]


@dataclass(frozen=True, slots=True)
class Dependency:
    name: str
    specs: tuple[str, ...]
    paths: tuple[str, ...]


def dependencies(found: Iterable[Declaration]) -> list[Dependency]:
    """The distributions declared, once each, with the specifiers and the files that declare them.
    A constraints file declares nothing."""
    names: dict[str, tuple[set[str], set[str]]] = {}
    for row in found:
        if not row.constraint:
            specs, paths = names.setdefault(row.name, (set(), set()))
            specs.update([row.spec] if row.spec else [])
            paths.add(row.path)
    return [
        Dependency(name, tuple(sorted(s)), tuple(sorted(p)))
        for name, (s, p) in sorted(names.items())
    ]


def current(specs: Sequence[str]) -> Version | None:
    """The release a declaration starts at: the one it pins, else its lower bound."""
    for text in specs:
        try:
            found = SpecifierSet(text)
        except InvalidSpecifier:
            continue
        pinned = [
            Version(one.version)
            for one in found
            if one.operator in ("==", "===") and "*" not in one.version
        ]
        floor = bounds(found)[0]
        if pinned or floor is not None:
            return pinned[0] if pinned else floor
    return None


def gap(now: Version | None, newest: Version | None) -> Gap:
    if now is None or newest is None:
        return "unknown"
    if newest.major != now.major:
        return "major" if newest > now else "none"
    if newest.minor != now.minor:
        return "minor" if newest > now else "none"
    return "patch" if newest > now else "none"


def judge(fetcher: Fetcher, one: Dependency, packs: Sequence[LoadedPack]) -> Row:
    """What the index says of one distribution; a question it cannot answer is the row's `error`."""
    now = current(one.specs)
    declared = ", ".join(one.specs) or None
    try:
        project = index.project(fetcher, one.name)
        newest = project.newest()
        facts = index.metadata(fetcher, one.name)
        used = index.metadata(fetcher, one.name, str(now)) if now is not None else None
    except NetworkError as error:
        reason = NOT_FOUND if error.reason == "not_found" else error.detail
        return Row(
            distribution=one.name,
            declared=declared,
            current=_text(now),
            newest=None,
            gap="unknown",
            flags=(),
            advisories=(),
            knowledge="none",
            pack=None,
            paths=one.paths,
            error=reason,
        )
    flags: list[Flag] = []
    if facts is not None and INACTIVE in facts.classifiers:
        flags.append("inactive")
    if (
        now is not None
        and project.of(now)
        and all(file.yanked is not None for file in project.of(now))
    ):
        flags.append("yanked")
    advisories = tuple(sorted(v.id for v in used.vulnerabilities)) if used is not None else ()
    if advisories:
        flags.append("advisory")
    pack = _bundled(one.name, now, packs)
    return Row(
        distribution=one.name,
        declared=declared,
        current=_text(now),
        newest=_text(newest),
        gap=gap(now, newest),
        flags=tuple(flags),
        advisories=advisories,
        knowledge="bundled" if pack else "synthesizable" if newest is not None else "none",
        pack=pack,
        paths=one.paths,
        error=None,
    )


def _text(version: Version | None) -> str | None:
    return None if version is None else str(version)


def _bundled(name: str, now: Version | None, packs: Sequence[LoadedPack]) -> str | None:
    """The id of a known pack that migrates `name` from the release in use."""
    for loaded in packs:
        side = loaded.pack.from_
        if canonicalize_name(side.package) == name and (
            now is None or now in SpecifierSet(side.version)
        ):
            return loaded.pack.id
    return None


def survey(fetcher: Fetcher, found: Sequence[Dependency], packs: Sequence[LoadedPack]) -> list[Row]:
    """A row for each dependency, asked about at once, worst first."""
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows = list(pool.map(lambda one: judge(fetcher, one, packs), found))
    return sorted(rows, key=_order)


def _order(row: Row) -> tuple[int, int, str]:
    rank = {"major": 0, "minor": 1, "patch": 2, "unknown": 3, "none": 4}
    return (0 if row.advisories else 1, rank[row.gap], row.distribution)


def unreachable(rows: Sequence[Row]) -> bool:
    """Whether the index answered none of the questions, for a reason other than not having the
    project (a private distribution is not on the public index)."""
    return (
        bool(rows)
        and all(row.error for row in rows)
        and any(row.error != NOT_FOUND for row in rows)
    )


def worth_showing(row: Row) -> bool:
    return bool(row.flags) or row.gap == "major" or row.error is not None


def table(rows: Sequence[Row]) -> list[str]:
    """The rows as aligned columns, with what to do about the first."""
    head = ("Distribution", "In use", "Newest", "Gap", "Notes", "Migrate with")
    body = [
        (
            row.distribution,
            row.current or "-",
            row.newest or "-",
            row.gap,
            _notes(row),
            _how(row),
        )
        for row in rows
    ]
    widths = [max(len(line[column]) for line in (head, *body)) for column in range(len(head))]
    return [
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in (head, *body)
    ]


def _notes(row: Row) -> str:
    """The flags, the first advisories (the rest only counted), and why the index did not answer."""
    shown, rest = row.advisories[:ADVISORIES_SHOWN], len(row.advisories) - ADVISORIES_SHOWN
    more = [f"+{rest} more"] if rest > 0 else []
    return "; ".join([*row.flags, *shown, *more, *([row.error] if row.error else [])]) or "-"


def _how(row: Row) -> str:
    if row.knowledge == "bundled":
        return f"bundled pack {row.pack}"
    return "two releases to compare" if row.knowledge == "synthesizable" else "-"


def next_step(rows: Sequence[Row]) -> str | None:
    """The command for the first row that has a way to migrate."""
    for row in rows:
        if row.knowledge == "bundled":
            return f"obelize fix --pack {row.pack}"
        if row.knowledge == "synthesizable" and row.error is None:
            return f"obelize upgrade {row.distribution}"
    return None


__all__ = [
    "Dependency",
    "Document",
    "Row",
    "current",
    "dependencies",
    "gap",
    "next_step",
    "survey",
    "table",
    "unreachable",
    "worth_showing",
]
