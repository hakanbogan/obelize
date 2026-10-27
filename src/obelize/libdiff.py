"""Compare two releases of a library as an index serves them: fetch both, read what each exports,
and say what changed. Nothing is installed, built or run (ADR-062).
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING

from packaging.version import InvalidVersion, Version

from obelize import index, release
from obelize.apidiff import diff as api
from obelize.apidiff import surface
from obelize.archive import ArchiveError

if TYPE_CHECKING:
    from obelize.apidiff.surface import Surface
    from obelize.net import Fetcher


# The most releases read between the two compared, to find what the library said before it removed.
MAX_BETWEEN = 6


class LibraryError(Exception):
    """A comparison that cannot be made, and why, in words for the person who asked."""


@dataclass(frozen=True, slots=True)
class Comparison:
    """Two releases, the module compared, what each exports and what changed."""

    old: index.File
    new: index.File
    module: str
    old_surface: Surface
    new_surface: Surface
    changes: tuple[api.ApiChange, ...]
    # The extras the newer release lists as `Provides-Extra`, from its METADATA (ADR-077).
    extras: tuple[str, ...] = ()


def version(text: str) -> Version:
    try:
        return Version(text)
    except InvalidVersion as error:
        raise LibraryError(f"{text!r} is not a version such as 1.4.2") from error


def newest(project: index.Project) -> Version:
    found = project.newest()
    if found is None:
        raise LibraryError(f"{project.name} has no release that is not withdrawn")
    return found


def compare(
    fetcher: Fetcher,
    project: index.Project,
    old: Version,
    new: Version,
    *,
    module: str | None = None,
    python: Version | None = None,
) -> Comparison:
    """What `new` changed in the API of `old`.

    A library warns before it removes, in the last release that still has the name, so the newest
    release of each minor line between the two is read too, newest first, until every name that left
    has been found in one or `MAX_BETWEEN` releases are read.
    """
    files = []
    for wanted in (old, new):
        file = project.choose(wanted, python)
        if file is None:
            raise LibraryError(f"{project.name} {wanted} has no file that can be read")
        files.append(file)
    try:
        with ExitStack() as stack:
            roots = [stack.enter_context(release.read(fetcher, file)).root for file in files]
            chosen = module or _shared(project.name, [surface.modules(root) for root in roots])
            before, after = (surface.read(root, chosen) for root in roots)
            extras = release.provides_extras(roots[1])
            passed: list[Surface] = []
            left = {one.path for one in api.diff(before, after) if one.type != "unseen"}
            for file in _lines(project, old, new, python):
                if not left:
                    break
                try:
                    root = stack.enter_context(release.read(fetcher, file)).root
                    passed.append(surface.read(root, chosen))
                except surface.SurfaceError:
                    continue
                left -= set(passed[-1].relative())
    except (ArchiveError, release.ReleaseError, surface.SurfaceError) as error:
        raise LibraryError(str(error)) from error
    return Comparison(
        files[0],
        files[1],
        chosen,
        before,
        after,
        api.diff(before, after, before=passed),
        extras,
    )


def _lines(
    project: index.Project, old: Version, new: Version, python: Version | None
) -> list[index.File]:
    """The file of the newest final release of each minor line between `old` and `new`, newest
    first."""
    lines: dict[tuple[int, int], index.File] = {}
    for found in sorted(project.versions, reverse=True):
        file = project.choose(found, python)
        if file is not None and old < found < new and not found.is_prerelease:
            lines.setdefault((found.major, found.minor), file)
    return list(lines.values())[:MAX_BETWEEN]


def _shared(name: str, found: list[tuple[str, ...]]) -> str:
    common = sorted(set(found[0]).intersection(*found[1:]))
    if len(common) == 1:
        return common[0]
    wanted = name.lower().replace("-", "_")
    if wanted in common:
        return wanted
    if not common:
        raise LibraryError(
            f"the releases of {name} have no module in common ({', '.join(found[0]) or 'none'} "
            f"in the first): name the module with --module"
        )
    raise LibraryError(
        f"{name} has more than one module, {', '.join(common)}: name one with --module"
    )


__all__ = ["Comparison", "LibraryError", "compare", "newest", "version"]
