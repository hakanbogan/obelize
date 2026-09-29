"""The file primitives on POSIX: each name is opened relative to a directory descriptor."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import NewType

assert sys.platform != "win32"  # noqa: S101 - `mypy --platform win32` reads no further

# An open directory, the descriptor itself. Windows' is an NT handle no `os` call takes, so the
# win32 type check holds callers to passing it back here.
Handle = NewType("Handle", int)


def root(path: Path) -> Handle:
    """The user's root directory, followed if it is a link (`/tmp` on macOS)."""
    return Handle(os.open(path, os.O_RDONLY | os.O_DIRECTORY))


def directory(parent: Handle, name: str) -> Handle:
    """A directory in `parent`; a link or a non-directory fails with `ELOOP` or `ENOTDIR`."""
    return Handle(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent))


def make_directory(parent: Handle, name: str) -> None:
    os.mkdir(name, dir_fd=parent)


def open_path(path: Path) -> int:
    """A file to read; a link at the last component fails with `ELOOP`, one above it is followed."""
    return os.open(path, os.O_RDONLY | os.O_NOFOLLOW)


def open_at(parent: Handle, name: str) -> int:
    """A file in `parent` to read; a link at the name fails with `ELOOP`."""
    return os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)


def create(parent: Handle, name: str, mode: int) -> int:
    """A new file in `parent` to write. `O_EXCL` fails on any name that exists, a link included."""
    return os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode, dir_fd=parent)


def status(parent: Handle, name: str) -> os.stat_result:
    """The name's own status: a link is described, not followed."""
    return os.stat(name, dir_fd=parent, follow_symlinks=False)


def set_mode(descriptor: int, mode: int) -> None:
    os.fchmod(descriptor, mode)


def rename(parent: Handle, source: str, target: str) -> None:
    """Replace `target` by `source` in `parent`; a link at `target` is replaced, not followed."""
    os.replace(source, target, src_dir_fd=parent, dst_dir_fd=parent)


def unlink(parent: Handle, name: str) -> None:
    os.unlink(name, dir_fd=parent)


def remove_tree(parent: Handle, name: str) -> None:
    """Delete a directory tree; with a `dir_fd`, `shutil.rmtree` follows no link below it."""
    shutil.rmtree(name, dir_fd=parent)


def close(handle: Handle) -> None:
    os.close(handle)


def reserved(path: str) -> bool:
    """Whether a name in `path` opens something other than a file of that name: never here."""
    return False


__all__ = [
    "Handle",
    "close",
    "create",
    "directory",
    "make_directory",
    "open_at",
    "open_path",
    "remove_tree",
    "rename",
    "reserved",
    "root",
    "set_mode",
    "status",
    "unlink",
]
