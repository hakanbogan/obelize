"""Choose the paths a scan may read and report every refusal; the walker opens no file.

The byte prefilter, `max_file_bytes` and both parse gates belong to whoever reads the bytes, so
each file is read once. A silently dropped file would make "no findings" a false answer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from obelize import gitutil
from obelize.config import ConfigError, Selection
from obelize.fsutil import refusal
from obelize.models import Config, SkipReason
from obelize.native import files
from obelize.scan import manifests

# Recorded because only `git` honours `.gitignore`.
ListingSource = Literal["git", "walk"]

# Primary listing: tracked plus untracked files, minus the user's ignores. The walk sees ignored
# build output too, so where the two differ git is right.
GIT_LISTING = ("ls-files", "-z", "--cached", "--others", "--exclude-standard")

# A `.git` entry, file or directory, makes a directory another repository.
GIT_ENTRY = ".git"

# PEP 405 venv root marker: catches environments the always-excluded names miss.
VENV_MARKER = "pyvenv.cfg"

# One report sentence per SkipReason; a test pins the key set.
_DETAIL: dict[SkipReason, str] = {
    "missing": "Listed by git but missing from disk, usually a file deleted without git rm.",
    "not_a_file": (
        "Not a regular file, so there is nothing to parse. A submodule, for example, is "
        "listed by git as a single path."
    ),
    "outside_root": "Resolves outside the repository root, or does not resolve at all; skipped.",
    "submodule": "Has its own .git, so it is another repository; run obelize there.",
    "symlink": (
        "A symbolic link or a Windows junction; obelize does not follow links. Scan the "
        "target path instead."
    ),
    "unreadable": (
        "Could not be inspected: a directory could not be listed, or permissions hide the "
        "path. Check them before trusting a small finding count."
    ),
    "unusable_name": (
        "The name is not valid UTF-8 or contains a backslash, so no report can name it "
        "exactly, or Windows reserves it (a device such as aux.py, a ':' stream, a trailing "
        "dot or space); skipped."
    ),
}


@dataclass(frozen=True, slots=True)
class Skipped:
    """A refused path (repo-relative, `/`); run.json merges it with the reader's refusals."""

    path: str
    reason: SkipReason
    detail: str


# Suffixes that can hold Python but the default `include` does not take.
PYTHON_BEARING: Final = (".ipynb", ".pyi", ".pyw")


@dataclass(frozen=True, slots=True)
class Walk:
    """One selection pass; nothing in it has been opened. Every tuple is sorted by bytes."""

    source: ListingSource
    files: tuple[str, ...]
    # Taken by `include`, removed by the user's `exclude`. Those the prefilter matches are still
    # named: excluding a file from the scan does not exclude it from the install.
    excluded: tuple[str, ...]
    # Chosen by name, not `include` (default `**/*.py`), under the same `exclude` and path guard.
    # `setup.py` is here and in `files`: both passes read it and report different things.
    manifests: tuple[str, ...]
    skipped: tuple[Skipped, ...]
    # Not taken by `include` but can hold Python (notebook, stub, .pyw): not analysed, but the
    # manifest pin check prefilters their bytes, since they need the pin as much as a module does.
    unincluded: tuple[str, ...] = ()


def walk(root: Path, config: Config) -> Walk:
    if not root.is_dir():
        raise ConfigError(
            f"{root} is not a directory that can be read, so there is nothing to scan"
        )
    selection = Selection(config)
    skipped: list[Skipped] = []
    source: ListingSource = "git"
    listed = git_listing(root)
    if listed is None:
        source = "walk"
        listed, skipped = walk_listing(root, selection)

    files: list[str] = []
    excluded: list[str] = []
    found: list[str] = []
    unincluded: list[str] = []
    for name in listed:
        if not _usable(name):
            skipped.append(_skip(_printable(name), "unusable_name"))
            continue
        decision = selection.decide(name)
        manifest = manifests.is_manifest(name) and selection.selects_manifest(name)
        python = decision == "not_included" and name.endswith(PYTHON_BEARING)
        if not manifest and not python and decision in {"always_excluded", "not_included"}:
            continue
        # Stat only after matching, so a huge excluded tree costs no filesystem calls.
        reason = refusal(root, root / name)
        if reason is not None:
            skipped.append(_skip(name, reason))
            continue
        if manifest:
            found.append(name)
        if decision == "selected":
            files.append(name)
        elif decision == "excluded":
            excluded.append(name)
        elif python:
            unincluded.append(name)

    return Walk(
        source=source,
        files=tuple(sorted(files, key=os.fsencode)),
        excluded=tuple(sorted(excluded, key=os.fsencode)),
        manifests=tuple(sorted(found, key=os.fsencode)),
        skipped=tuple(sorted(skipped, key=lambda row: (os.fsencode(row.path), row.reason))),
        unincluded=tuple(sorted(unincluded, key=os.fsencode)),
    )


def git_listing(root: Path) -> list[str] | None:
    """Paths git lists under `root`, or `None` when the fallback walk must run.

    Also `None` below the toplevel: `git -C` would apply the enclosing repository's index and
    `.gitignore` to an unrelated tree.
    """
    if not gitutil.is_toplevel(root):
        return None
    listing = gitutil.run(root, *GIT_LISTING)
    if listing is None:
        return None
    return [name for name in listing.split("\0") if name]


def walk_listing(root: Path, selection: Selection) -> tuple[list[str], list[Skipped]]:
    """The fallback listing, which never follows links.

    A directory is dropped, in order: an unusable name (no pattern or report can name it), pruned
    by config (silently), a link (a Windows junction too, which `os.walk` descends), a submodule
    (its files belong to another repository's diff), a venv (silently; last, as it costs a stat).
    """
    paths: list[str] = []
    skipped: list[Skipped] = []

    def unreadable(error: OSError) -> None:
        failed = Path(error.filename) if error.filename else root
        skipped.append(_skip(_relative(root, failed), "unreadable"))

    for parent, directories, names in os.walk(root, onerror=unreadable, followlinks=False):
        here = Path(parent)
        keep: list[str] = []
        for name in sorted(directories):
            child = here / name
            relative = _relative(root, child)
            if not _usable(relative):
                skipped.append(_skip(_printable(relative), "unusable_name"))
                continue
            if selection.prunes_directory(relative):
                continue
            if os.path.islink(child) or os.path.isjunction(child):
                skipped.append(_skip(relative, "symlink"))
                continue
            if _exists(child / GIT_ENTRY):
                skipped.append(_skip(relative, "submodule"))
                continue
            if _exists(child / VENV_MARKER):
                continue
            keep.append(name)
        directories[:] = keep
        paths.extend(_relative(root, here / name) for name in sorted(names))
    return paths, skipped


def _exists(path: Path) -> bool:
    """False on a denial too, so the directory is kept and `os.walk` reports it `unreadable`.

    Deliberately not `Path.exists`, which raises on a denial before 3.14.
    """
    return os.path.exists(path)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _skip(path: str, reason: SkipReason) -> Skipped:
    return Skipped(path=path, reason=reason, detail=_DETAIL[reason])


def _usable(name: str) -> bool:
    """False for a non-UTF-8 name, a backslash (a separator elsewhere) or a reserved name."""
    if "\\" in name or files.reserved(name):
        return False
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _printable(name: str) -> str:
    """A `surrogateescape` name made printable, the same on every platform.

    Not `os.fsencode`: Windows encodes with `surrogatepass`, which spells the byte differently.
    A Windows listing can also hold a lone surrogate no byte decoded to; it prints as `\\ud800`.
    """
    try:
        data = name.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        return name.encode("utf-8", "backslashreplace").decode("utf-8")
    return data.decode("utf-8", "backslashreplace")


__all__ = [
    "GIT_LISTING",
    "PYTHON_BEARING",
    "ListingSource",
    "Skipped",
    "Walk",
    "git_listing",
    "walk",
    "walk_listing",
]
