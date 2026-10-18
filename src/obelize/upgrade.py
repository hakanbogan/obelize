"""`obelize upgrade`: the pack that moves one dependency from the release in use to a newer one.

A pack that is known (bundled, or in a directory of the user's own) wins; for a library that has
none, a pack is made from the public API of the two releases and kept, named by both, so the same
move is not read from the index twice (`obelize pack synth`, ADR-063).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from obelize import libdiff
from obelize.packs import loader
from obelize.packtools import synth

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from packaging.version import Version

    from obelize import index
    from obelize.net import Fetcher


@dataclass(frozen=True, slots=True)
class Chosen:
    """The pack to run: an id, or the path of a pack file, and how it came to be chosen."""

    reference: str
    note: str


def choose(
    fetcher: Fetcher,
    project: index.Project,
    now: Version,
    target: Version,
    *,
    targeted: bool,
    module: str | None,
    known: Sequence[loader.LoadedPack],
    kept: Path,
) -> Chosen:
    """A known pack that migrates `project` from `now` (and to `target`, if the person named one),
    else the pack made from the two releases, which is kept in `kept`."""
    for loaded in known:
        pack = loaded.pack
        if (
            canonicalize_name(pack.from_.package) == project.name
            and now in SpecifierSet(pack.from_.version)
            and (not targeted or target in SpecifierSet(pack.to.version))
        ):
            return Chosen(pack.id, f"Using the pack {pack.id}.")
    folder = kept / synth.pack_id(project.name, now, target)
    if (folder / loader.PACK_FILENAME).is_file():
        return Chosen(
            str(folder / loader.PACK_FILENAME),
            "Using the pack made from these two releases before.",
        )
    compared = libdiff.compare(fetcher, project, now, target, module=module)
    made = synth.make(
        kept,
        synth.request(project.name, now, target, compared),
        compared.old_surface,
        compared.changes,
    )
    names = sum(made.covered.values()) - made.covered.get("dependency-line", 0)
    return Chosen(
        str(made.folder / loader.PACK_FILENAME),
        f"Made a pack from the public API of {project.name} {now} and {target}: {names} name(s).",
    )


__all__ = ["Chosen", "choose"]
