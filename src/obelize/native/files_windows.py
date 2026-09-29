"""The file primitives on Windows: NT calls relative to an open directory handle.

Below the root every name is opened with `FILE_OPEN_REPARSE_POINT`, so a symbolic link or a
junction is opened as itself: refused where a directory or a file to read is asked for, and
replaced or deleted as itself, never followed.
"""

from __future__ import annotations

import _winapi
import errno
import msvcrt
import os
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from obelize.native import _win32
from obelize.native.windows_names import reserved

assert sys.platform == "win32"  # noqa: S101 - `mypy` for another platform reads no further

_DIRECTORY = _win32.FILE_LIST_DIRECTORY | _win32.FILE_TRAVERSE | _win32.FILE_READ_ATTRIBUTES
# The attributes too: the classic delete clears a read-only one first.
_DELETING = _win32.DELETE | _win32.FILE_READ_ATTRIBUTES | _win32.FILE_WRITE_ATTRIBUTES
_EMPTYING = _DELETING | _win32.FILE_LIST_DIRECTORY
# `set_mode` reads the attributes it keeps.
_WRITING = _win32.FILE_GENERIC_WRITE | _win32.FILE_READ_ATTRIBUTES


@dataclass(frozen=True, slots=True)
class Handle:
    """An open directory, whose NT handle `os.fstat` and `os.close` would take for a C runtime
    descriptor.

    `posix` is its volume's answer to whether a rename or a delete takes POSIX semantics, asked
    once at the root: a mount point is a junction, so everything below a root is on its volume.
    """

    value: int
    posix: bool


def root(path: Path) -> Handle:
    """The user's root directory, followed if it is a link or a junction."""
    value = _winapi.CreateFile(
        str(path),
        _DIRECTORY | _win32.SYNCHRONIZE,
        _win32.FILE_SHARE_ALL,
        0,
        _winapi.OPEN_EXISTING,
        _win32.FILE_FLAG_BACKUP_SEMANTICS,
        0,
    )
    with _win32.closed_on_error(value):
        attributes, _ = _win32.attribute_tag(value, str(path))
        if not attributes & _win32.FILE_ATTRIBUTE_DIRECTORY:
            raise NotADirectoryError(errno.ENOTDIR, os.strerror(errno.ENOTDIR), str(path))
        return Handle(value, _win32.posix_semantics(value, str(path)))


def directory(parent: Handle, name: str) -> Handle:
    """A directory in `parent`; a link fails with `ELOOP`, a file with `ENOTDIR`."""
    return Handle(_unlinked(parent, name, _DIRECTORY, _win32.FILE_DIRECTORY_FILE), parent.posix)


def make_directory(parent: Handle, name: str) -> None:
    created = _win32.open_at(
        parent.value,
        name,
        _win32.FILE_LIST_DIRECTORY,
        _win32.FILE_CREATE,
        _win32.FILE_DIRECTORY_FILE,
        attributes=_win32.FILE_ATTRIBUTE_NORMAL,
    )
    _win32.close(created)


def open_path(path: Path) -> int:
    """A file to read; a link at the last component fails with `ELOOP`, one above it is followed."""

    def opened(flags: int) -> int:
        return _winapi.CreateFile(
            str(path),
            _win32.FILE_GENERIC_READ,
            _win32.FILE_SHARE_ALL,
            0,
            _winapi.OPEN_EXISTING,
            flags,
            0,
        )

    unfollowed = opened(_win32.FILE_FLAG_OPEN_REPARSE_POINT)
    return _descriptor(_checked(unfollowed, str(path), lambda: opened(0)))


def open_at(parent: Handle, name: str) -> int:
    """A file in `parent` to read; a link at the name fails with `ELOOP`."""
    return _descriptor(
        _unlinked(parent, name, _win32.FILE_GENERIC_READ, _win32.FILE_NON_DIRECTORY_FILE)
    )


def create(parent: Handle, name: str, mode: int) -> int:
    """A new file in `parent` to write; any name that exists fails, a link included.

    Of `mode` Windows would keep only the write bit, which both callers set.
    """
    created = _win32.open_at(
        parent.value,
        name,
        _WRITING,
        _win32.FILE_CREATE,
        _win32.FILE_NON_DIRECTORY_FILE,
        attributes=_win32.FILE_ATTRIBUTE_NORMAL,
    )
    return _descriptor(created)


def status(parent: Handle, name: str) -> os.stat_result:
    """The name's own kind, read-only bit and reparse tag: a link is described, not followed."""
    value = _win32.open_at(parent.value, name, _win32.FILE_READ_ATTRIBUTES, _win32.FILE_OPEN, 0)
    try:
        attributes, tag = _win32.attribute_tag(value, name)
    finally:
        _win32.close(value)
    return _win32.stat_result(attributes, tag)


def set_mode(descriptor: int, mode: int) -> None:
    """The write bit, as the read-only attribute: Windows keeps no other."""
    handle = msvcrt.get_osfhandle(descriptor)
    _win32.set_attributes(handle, readonly=not mode & stat.S_IWRITE, name=None)


def rename(parent: Handle, source: str, target: str) -> None:
    """Replace `target` by `source` in `parent`; a link at `target` is replaced, not followed.

    A directory at `target` is `EISDIR`, as POSIX says, where NTFS says only access denied.
    """
    _refuse_a_directory(parent, target)
    value = _win32.open_at(parent.value, source, _win32.DELETE, _win32.FILE_OPEN, 0)
    try:
        _win32.rename(value, parent.value, target, posix=parent.posix)
    finally:
        _win32.close(value)


def unlink(parent: Handle, name: str) -> None:
    value = _win32.open_at(
        parent.value, name, _DELETING, _win32.FILE_OPEN, _win32.FILE_NON_DIRECTORY_FILE
    )
    _deleted(value, name, posix=parent.posix)


def remove_tree(parent: Handle, name: str) -> None:
    """Delete a directory tree, listed from each directory's handle, never by path.

    A link below the name, a junction included, is opened as itself and deleted as itself: its
    own directory is empty, so nothing it names is listed.
    """
    opened = _unlinked(parent, name, _EMPTYING, _win32.FILE_DIRECTORY_FILE)
    _emptied(opened, name, posix=parent.posix)


def close(handle: Handle) -> None:
    _win32.close(handle.value)


def _unlinked(parent: Handle, name: str, access: int, options: int) -> int:
    """`name` in `parent`, refused with `ELOOP` if it is a link."""

    def opened(*, follow: bool) -> int:
        return _win32.open_at(parent.value, name, access, _win32.FILE_OPEN, options, follow=follow)

    return _checked(opened(follow=False), name, lambda: opened(follow=True))


def _checked(value: int, name: str, reopen: Callable[[], int]) -> int:
    """`value`, unless it holds a reparse point.

    One that names another path, a symbolic link or a junction, fails with `ELOOP`. Any other,
    such as a OneDrive placeholder, is opened again through its filter, which must give the file
    `value` holds.
    """
    with _win32.closed_on_error(value):
        attributes, tag = _win32.attribute_tag(value, name)
        if not attributes & _win32.FILE_ATTRIBUTE_REPARSE_POINT:
            return value
    try:
        if tag & _win32.NAME_SURROGATE:
            raise OSError(errno.ELOOP, "Is a symbolic link or a junction", name)
        return _same(value, reopen(), name)
    finally:
        _win32.close(value)


def _same(held: int, followed: int, name: str) -> int:
    with _win32.closed_on_error(followed):
        if _win32.identity(followed, name) != _win32.identity(held, name):
            raise OSError(errno.ELOOP, "Became another file while it was opened", name)
    return followed


def _descriptor(value: int) -> int:
    """A C runtime descriptor that owns `value`, binary since no `O_TEXT` is asked for."""
    with _win32.closed_on_error(value):
        return msvcrt.open_osfhandle(value, 0)


def _refuse_a_directory(parent: Handle, name: str) -> None:
    try:
        kind = status(parent, name).st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(kind):
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), name)


def _emptied(value: int, name: str, *, posix: bool) -> None:
    """Delete everything in the open directory `value`, then it, and close it."""
    try:
        for child, attributes in _win32.listing(value, name):
            if attributes & _win32.FILE_ATTRIBUTE_DIRECTORY:
                below = _win32.open_at(
                    value, child, _EMPTYING, _win32.FILE_OPEN, _win32.FILE_DIRECTORY_FILE
                )
                _emptied(below, child, posix=posix)
            else:
                below = _win32.open_at(
                    value, child, _DELETING, _win32.FILE_OPEN, _win32.FILE_NON_DIRECTORY_FILE
                )
                _deleted(below, child, posix=posix)
        _win32.delete(value, posix=posix, name=name)
    finally:
        _win32.close(value)


def _deleted(value: int, name: str, *, posix: bool) -> None:
    try:
        _win32.delete(value, posix=posix, name=name)
    finally:
        _win32.close(value)


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
