"""Path safety shared by the scanner (reads) and the codemod (writes), so both get one answer.

Containment resolves the root as well as the candidate: on macOS /tmp, /var and /etc are
symlinks, and resolving only one side silently finds nothing. `apply` checks every path before
writing any; `write` re-checks on its own and descends with O_NOFOLLOW, since rename resolves
every directory above the final name.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, get_args

from obelize import gitutil
from obelize.models import PathRefusal
from obelize.native import files

# Why a planned replacement was not written: PathRefusal's five reasons plus a writer-only one.
WriteRefusal = Literal[
    "file_changed_since_read",
    "missing",
    "not_a_file",
    "outside_root",
    "symlink",
    "unreadable",
]
WRITE_REFUSALS: frozenset[WriteRefusal] = frozenset(get_args(WriteRefusal))

# Not `.py`: a temp file left by a crash must not be scanned as source.
TEMPORARY_SUFFIX = ".obelize-tmp"


@dataclass(frozen=True, slots=True)
class Change:
    """One planned replacement; a file differing from `before` changed mid-run and is refused.

    The dirty-tree gate cannot see such an edit.
    """

    path: str
    before: bytes
    after: bytes


@dataclass(frozen=True, slots=True)
class Written:
    """One file written, with the two hashes `run.json` records."""

    path: str
    before_sha256: str
    after_sha256: str


@dataclass(frozen=True, slots=True)
class Refused:
    path: str
    reason: WriteRefusal


@dataclass(frozen=True, slots=True)
class Apply:
    """What one `--apply` did; `dirty`/`unknown` is set only when it is why nothing was written."""

    written: tuple[Written, ...] = ()
    refused: tuple[Refused, ...] = ()
    dirty: tuple[str, ...] = ()
    # git could not say whether the tree is clean: refused exactly like a dirty tree.
    unknown: bool = False
    # Every `dirty` path is a planned file git does not track, which `git stash` leaves in place.
    untracked: bool = False

    @property
    def blocked(self) -> bool:
        """Whether something stopped this run (exit code 5)."""
        return bool(self.dirty or self.refused or self.unknown)


def contained(root: Path, candidate: Path) -> bool:
    """Whether `candidate` is inside `root`, both resolved; a dangling link or loop is a refusal.

    The root is resolved per call on purpose: a cached one could go stale.
    """
    try:
        return candidate.resolve(strict=True).is_relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError):
        return False


def refusal(root: Path, candidate: Path) -> PathRefusal | None:
    """Why `candidate` must not be opened, or `None` when it may be.

    Links, Windows junctions included, are refused before containment: even an in-repo link
    would be scanned twice and rewritten under a name its author did not use. The regular-file
    check drops gitlinks (submodules are directories), fifos and devices. A listed path that was
    `rm`ed is `missing`, not `outside_root`. The errno is read directly: 3.14's `Path.exists`
    hides a denial.
    """
    try:
        status = candidate.lstat()
    except OSError as error:
        return "missing" if error.errno in _ABSENT else "unreadable"
    if linked(status):
        return "symlink"
    if not contained(root, candidate):
        return "outside_root"
    if not stat.S_ISREG(status.st_mode):
        return "not_a_file"
    return None


# lstat errnos meaning nothing is there (pathlib's set up to 3.13, minus the impossible `EBADF`).
_ABSENT = frozenset({errno.ENOENT, errno.ENOTDIR, errno.ELOOP})

# Set in the reparse tag of a Windows symlink or junction, which name another path; not in a
# OneDrive placeholder's, which is the file itself.
_NAME_SURROGATE = 0x20000000


def linked(status: os.stat_result) -> bool:
    """Whether an `lstat` answer is a link: `S_ISLNK` calls a Windows junction a directory."""
    tag: int = getattr(status, "st_reparse_tag", 0)
    return stat.S_ISLNK(status.st_mode) or bool(tag & _NAME_SURROGATE)


def sha256(data: bytes) -> str:
    """The hex digest `run.json` records."""
    return hashlib.sha256(data).hexdigest()


def read(absolute: Path) -> bytes:
    """Read a file, failing with `ELOOP` if it became a symlink after `refusal` checked it.

    Unlike `write`, only the last component is guarded: a scan opens every file, so a per-directory
    descent is too costly, and a raced read misreports while a raced write damages a tree.
    """
    descriptor = files.open_path(absolute)
    with os.fdopen(descriptor, "rb") as handle:
        return handle.read()


def write(root: Path, path: str, data: bytes) -> PathRefusal | None:
    """Atomically replace `path` under `root` with `data`, or say why it was not replaced.

    The temporary sits beside the target: rename is atomic only within one filesystem, and a copy
    fallback is the half-written file this prevents. The guard is re-asked here. Never returns
    `file_changed_since_read`; `obelize undo` relies on that.
    """
    if unusable(path):
        return "outside_root"
    reason = refusal(root, root / path)
    if reason is not None:
        return reason
    try:
        _replace(root, path, data)
    except OSError:
        return "unreadable"
    return None


def gate(root: Path, changes: Sequence[Change], *, allow_dirty: bool = False) -> Apply | None:
    """`apply`'s first two gates without writing; `None` means nothing refuses the plan yet.

    `fix --apply` asks early so a refused apply runs no baseline; `apply` re-asks and decides.
    """
    if not allow_dirty:
        try:
            found = gitutil.tree(root, [change.path for change in changes])
        except gitutil.UnansweredError:
            return Apply(unknown=True)
        if found is not None and (found.modified or found.untracked):
            return Apply(
                dirty=tuple(sorted({*found.modified, *found.untracked})),
                untracked=not found.modified,
            )
    stopped = tuple(
        row
        for row in (
            _preflight(root, change) for change in sorted(changes, key=lambda change: change.path)
        )
        if row is not None
    )
    return Apply(refused=stopped) if stopped else None


def apply(root: Path, changes: Sequence[Change], *, allow_dirty: bool = False) -> Apply:
    """Write a run's changes, or say why none were written. Gates, in order (1-2 are `gate`):

    1. Tree: uncommitted work anywhere, or a file on the plan git does not track, refuses it
       all, so `git diff` is the migration. Outside a repository nothing is refused; a
       repository git cannot describe is.
    2. Every path (guard, staleness) before any write, so a refusal leaves the tree unchanged.
    3. The write: only a race fails here, and each file already written is complete.
    """
    stopped = gate(root, changes, allow_dirty=allow_dirty)
    if stopped is not None:
        return stopped
    ordered = sorted(changes, key=lambda change: change.path)
    written: list[Written] = []
    refused: list[Refused] = []
    for change in ordered:
        reason = write(root, change.path, change.after)
        if reason is not None:
            refused.append(Refused(path=change.path, reason=reason))
            continue
        written.append(
            Written(
                path=change.path,
                before_sha256=sha256(change.before),
                after_sha256=sha256(change.after),
            )
        )
    return Apply(written=tuple(written), refused=tuple(refused))


def _preflight(root: Path, change: Change) -> Refused | None:
    """The guard and the staleness check for one change."""
    if unusable(change.path):
        return Refused(path=change.path, reason="outside_root")
    absolute = root / change.path
    reason = refusal(root, absolute)
    if reason is not None:
        return Refused(path=change.path, reason=reason)
    try:
        current = read(absolute)
    except OSError:
        return Refused(path=change.path, reason="unreadable")
    if current != change.before:
        return Refused(path=change.path, reason="file_changed_since_read")
    return None


def unusable(path: str) -> bool:
    """Absolute, empty or `..` paths, and names this system opens as something else.

    `root / "/etc/x"` is `/etc/x`, a descent follows `..`, and Windows opens `aux.py` as a device.
    """
    parts = PurePosixPath(path).parts
    absolute = PurePosixPath(path).is_absolute()
    return absolute or not parts or ".." in parts or files.reserved(path)


def _replace(root: Path, path: str, data: bytes) -> None:
    """Write into the file's own directory and rename over it."""
    parts = PurePosixPath(path).parts
    directory = _descend(root, parts[:-1])
    try:
        _through(directory, parts[-1], data)
    finally:
        files.close(directory)


def _descend(root: Path, parts: tuple[str, ...]) -> files.Handle:
    """Open the file's directory one name at a time, with `O_NOFOLLOW` below the root.

    The root may be a symlink (`/tmp` on macOS). Below it, rename would resolve a `pkg` swapped for
    a link to `/etc` between plan and write, and write into `/etc`.
    """
    handle = files.root(root)
    for part in parts:
        try:
            below = files.directory(handle, part)
        finally:
            files.close(handle)
        handle = below
    return handle


def _through(directory: files.Handle, name: str, data: bytes) -> None:
    """Temporary file, fsync, original mode, rename.

    The mode is copied so `0600` never strips an executable bit. Only the file is fsynced: this
    survives a crash or kill, not a power cut.
    """
    mode = files.status(directory, name).st_mode & 0o7777
    temporary = f".{name}.{uuid.uuid4().hex}{TEMPORARY_SUFFIX}"
    descriptor = files.create(directory, temporary, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            files.set_mode(handle.fileno(), mode)
        files.rename(directory, temporary, name)
    finally:
        _discard(directory, temporary)


def _discard(directory: files.Handle, temporary: str) -> None:
    """Remove the temporary unless the rename already moved it."""
    try:
        files.unlink(directory, temporary)
    except FileNotFoundError:
        return


__all__ = [
    "TEMPORARY_SUFFIX",
    "WRITE_REFUSALS",
    "Apply",
    "Change",
    "Refused",
    "WriteRefusal",
    "Written",
    "apply",
    "contained",
    "gate",
    "linked",
    "read",
    "refusal",
    "sha256",
    "unusable",
    "write",
]
