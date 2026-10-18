"""The scratch copy: the files git lists, byte for byte, in a directory that is new.

Nothing else is copied: not `.git`, not an environment, not a link (which could point out of the
repository), not a file that is not a regular one. The copy is a repository of its own with one
commit, so that `obelize fix --apply` finds a clean tree there; git is told to use no template and
to run no hook.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from obelize import gitutil
from obelize.config import Selection
from obelize.models import Config
from obelize.scan import walker

if TYPE_CHECKING:
    from pathlib import Path

# What a trial refuses to copy: more than a repository of source holds.
FILE_LIMIT: Final = 200_000
BYTE_LIMIT: Final = 2 << 30
_GIT: Final = ("-c", "user.name=obelize", "-c", "user.email=obelize@invalid")


class CopyError(Exception):
    """A repository that cannot be copied, and why."""


@dataclass(frozen=True, slots=True)
class Copied:
    files: int
    size: int
    # Names left out because they are not regular files (links, devices).
    left: tuple[str, ...]


def make(root: Path, into: Path) -> Copied:
    """Copy `root` into the new directory `into`, and make it a one-commit repository."""
    names = walker.git_listing(root)
    if names is None:
        names, _ = walker.walk_listing(root, Selection(Config()))
    into.mkdir(mode=0o700, parents=True)
    files = size = 0
    left: list[str] = []
    for name in sorted(set(names)):
        if _excluded(name):
            continue
        source = root / name
        try:
            status = source.lstat()
        except OSError:
            left.append(name)
            continue
        if not stat.S_ISREG(status.st_mode):
            left.append(name)
            continue
        files += 1
        size += status.st_size
        if files > FILE_LIMIT or size > BYTE_LIMIT:
            raise CopyError(f"{root} is larger than a trial copies: {FILE_LIMIT} files or 2 GiB")
        target = into / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if status.st_mode & 0o111:
            target.chmod(0o755)
    _commit(into)
    return Copied(files, size, tuple(left))


def _excluded(name: str) -> bool:
    """A path a copy leaves out: a git directory, the run folders, caches, a name that leaves."""
    parts = name.split("/")
    return os.path.isabs(name) or bool({"..", ".git", ".obelize", "__pycache__"} & set(parts))


def _commit(into: Path) -> None:
    for arguments in (
        ("init", "-q", "--template="),
        ("add", "-A"),
        (
            *_GIT,
            "-c",
            "core.hooksPath=",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "copy",
        ),
    ):
        if gitutil.run(into, *arguments) is None:
            raise CopyError(f"git {arguments[0]} failed in the copy")
