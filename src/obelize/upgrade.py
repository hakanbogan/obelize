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
from obelize.packtools import synth, uses

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from packaging.version import Version

    from obelize import index
    from obelize.net import Fetcher
    from obelize.packs.schema import PackDocument


@dataclass(frozen=True, slots=True)
class Chosen:
    """The pack to run: an id, or the path of a pack file, how it came to be chosen, and what a
    trial installs to stand for the release moved to (and the distribution it replaces)."""

    reference: str
    note: str
    install: str
    remove: str | None = None


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
    root: Path | None = None,
) -> Chosen:
    """A known pack that migrates `project` from `now` (and to `target`, if the person named one),
    else the pack made from the two releases, which is kept in `kept`. A library that changed too
    much to flag name by name gets a pack for the names the code under `root` uses."""
    for loaded in known:
        pack = loaded.pack
        if (
            canonicalize_name(pack.from_.package) == project.name
            and now in SpecifierSet(pack.from_.version)
            and (not targeted or target in SpecifierSet(pack.to.version))
        ):
            return Chosen(
                pack.id, f"Using the pack {pack.id}.", *_installs(pack, project, target, targeted)
            )
    folder = kept / synth.pack_id(project.name, now, target)
    if (folder / loader.PACK_FILENAME).is_file():
        return Chosen(
            str(folder / loader.PACK_FILENAME),
            "Using the pack made from these two releases before.",
            f"{project.name}=={target}",
        )
    big = folder.with_name(f"{folder.name}.too-large")
    if root is not None and big.is_file():
        used = uses.names(root, big.read_text(encoding="utf-8").strip())
        if used is not None:
            again = kept / synth.pack_id(project.name, now, target, used) / loader.PACK_FILENAME
            if again.is_file():
                return Chosen(
                    str(again),
                    "Using the pack made for the names this repository uses before.",
                    f"{project.name}=={target}",
                )
    compared = libdiff.compare(fetcher, project, now, target, module=module)
    scope: frozenset[str] | None = None
    scoped = ""
    while True:
        wanted = synth.request(project.name, now, target, compared, scope)
        try:
            made = synth.make(
                kept, wanted, compared.old_surface, compared.changes, compared.new_surface
            )
        except synth.SynthTooLargeError as error:
            big.parent.mkdir(parents=True, exist_ok=True)
            big.write_text(compared.module + "\n", encoding="utf-8")
            used = uses.names(root, compared.module) if root is not None and scope is None else None
            if used is None:
                raise
            if not used:
                raise synth.SynthError(
                    f"{error} No import this repository makes reaches any of them, so there is "
                    f"nothing to flag."
                ) from error
            scope, scoped = used, f" {error} It flags the {len(used)} name(s) this repository uses."
            continue
        break
    names = sum(made.covered.values()) - made.covered.get("dependency-line", 0)
    return Chosen(
        str(made.folder / loader.PACK_FILENAME),
        f"Made a pack from the public API of {project.name} {now} and {target}: {names} name(s)."
        f"{scoped}",
        f"{project.name}=={target}",
    )


def _installs(
    pack: PackDocument, project: index.Project, target: Version, targeted: bool
) -> tuple[str, str | None]:
    """What the environment of a known pack's target holds: the release named, or the pack's own
    range; and the distribution it replaces, if it is another."""
    moved = canonicalize_name(pack.to.package) != project.name
    if targeted and not moved:
        return f"{pack.to.package}=={target}", None
    return f"{pack.to.package}{pack.to.version}", project.name if moved else None


__all__ = ["Chosen", "choose"]
