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
from obelize.packtools import guided, synth, uses

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from packaging.version import Version

    from obelize import index
    from obelize.net import Fetcher


@dataclass(frozen=True, slots=True)
class Chosen:
    """The pack to run: an id, or the path of a pack file, how it came to be chosen, and what a
    trial installs to stand for the release moved to (and the distribution it replaces)."""

    reference: str
    note: str
    install: str
    remove: str | None = None
    # What became of the claims a guide gave, when the pack was made with one in this run.
    claims: guided.Outcome | None = None


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
    guides: Callable[[], guided.Source | None] | None = None,
    say: Callable[[str], None] = lambda _line: None,
) -> Chosen:
    """A known pack that migrates `project` from `now` (and to `target`, if the person named one),
    else the pack made from the two releases, which is kept in `kept`. A library that changed too
    much to flag name by name gets a pack for the names the code under `root` uses. A pack made
    here takes the claims a model drafts from the guides `guides` reads, which are read, and asked
    about, once and only when no pack is known."""
    for loaded in known:
        pack = loaded.pack
        old, new = pack.from_, pack.to
        # A side that is the Python moves no dependency, so a pack of one is run by name.
        if (
            old.package
            and old.version
            and new.package
            and new.version
            and canonicalize_name(old.package) == project.name
            and now in SpecifierSet(old.version)
            and (not targeted or target in SpecifierSet(new.version))
        ):
            return Chosen(
                pack.id,
                f"Using the pack {pack.id}."
                + (" The pack is already known; --guide is not used." if guides else ""),
                *_installs(new.package, new.version, project, target, targeted),
            )
    source = guides() if guides is not None else None
    digest = source.digest if source is not None else None
    folder = kept / synth.pack_id(project.name, now, target, guide=digest)
    if (folder / loader.PACK_FILENAME).is_file():
        return Chosen(
            str(folder / loader.PACK_FILENAME),
            "Using the pack made from these two releases"
            f"{' and the guide' if source else ''} before.",
            f"{project.name}=={target}",
        )
    big = folder.with_name(f"{folder.name}.too-large")
    if root is not None and big.is_file():
        used = uses.names(root, big.read_text(encoding="utf-8").strip())
        if used is not None:
            again = (
                kept / synth.pack_id(project.name, now, target, used, digest) / loader.PACK_FILENAME
            )
            if again.is_file():
                return Chosen(
                    str(again),
                    "Using the pack made for the names this repository uses before.",
                    f"{project.name}=={target}",
                )
    compared = libdiff.compare(fetcher, project, now, target, module=module)
    scope: frozenset[str] | None = None
    scoped = ""
    drafted: guided.Drafted | None = None
    while True:
        wanted = synth.request(project.name, now, target, compared, scope, digest)
        if source is not None and drafted is None:
            synth.free(kept, wanted)
            told = guided.Names(project.name, str(now), str(target), compared.module)
            drafted = source.draft(told, say)
        try:
            made = synth.make(
                kept,
                wanted,
                compared.old_surface,
                compared.changes,
                compared.new_surface,
                drafted,
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
        claims=made.guided,
    )


def runtime_pack(known: Sequence[loader.LoadedPack], name: str) -> str | None:
    """The id of a known pack that migrates the module `name` off the Python itself or setuptools,
    for a name that is no dependency: the pack is run by its id."""
    return next(
        (
            loaded.pack.id
            for loaded in known
            if loaded.pack.to.package is None and name in loaded.pack.match.imports
        ),
        None,
    )


def moves_off(known: Sequence[loader.LoadedPack], name: str, now: Version) -> str | None:
    """The id of a known pack that moves the code of release `now` of `name` onto the Python
    itself: there is no release to move to, so `upgrade` says to run the pack and does not."""
    return next(
        (
            loaded.pack.id
            for loaded in known
            if loaded.pack.to.package is None
            and loaded.pack.from_.package
            and canonicalize_name(loaded.pack.from_.package) == name
            and now in loaded.pack.from_.versions()
        ),
        None,
    )


def _installs(
    package: str, version: str, project: index.Project, target: Version, targeted: bool
) -> tuple[str, str | None]:
    """What the environment of a known pack's target holds: the release named, or the pack's own
    range; and the distribution it replaces, if it is another."""
    moved = canonicalize_name(package) != project.name
    if targeted and not moved:
        return f"{package}=={target}", None
    return f"{package}{version}", project.name if moved else None


__all__ = ["Chosen", "choose", "moves_off", "runtime_pack"]
