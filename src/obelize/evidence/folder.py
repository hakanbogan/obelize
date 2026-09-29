"""An existing run folder, reached one directory at a time and never through a link.

A committed `.obelize/` can make any component a symlink, so each directory is opened relative
to its parent with O_NOFOLLOW and each file is renamed into place. Only the repository root is
followed. `run_dir.write` does not use this for the run folder: it creates a fresh random id.
"""

from __future__ import annotations

import contextlib
import errno
import os
import secrets
import stat
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from obelize import fsutil
from obelize.native import files

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator
    from pathlib import Path

# A link or non-directory: macOS answers ENOTDIR to O_DIRECTORY | O_NOFOLLOW, others ELOOP.
_REFUSED = (errno.ELOOP, errno.ENOTDIR)


@contextlib.contextmanager
def _refusing(name: str) -> Iterator[None]:
    try:
        yield
    except OSError as error:
        if error.errno not in _REFUSED:
            raise
        raise OSError(
            error.errno,
            f"{name} is a symbolic link or not a directory, and obelize does not read or "
            f"write through links; remove it",
        ) from error


@contextlib.contextmanager
def _opened(parent: files.Handle, name: str, *, create: bool) -> Iterator[files.Handle]:
    if create:
        with contextlib.suppress(FileExistsError):
            files.make_directory(parent, name)
    with _refusing(name):
        opened = files.directory(parent, name)
    try:
        yield opened
    finally:
        files.close(opened)


class RunFolder:
    """`<root>/<components...>` by handle; each call re-walks from the root and keeps none open."""

    def __init__(self, root: Path, *components: str) -> None:
        self.root = root
        self.components = components

    @contextlib.contextmanager
    def _directory(
        self, relative: tuple[str, ...], *, create: bool = False
    ) -> Iterator[files.Handle]:
        """The folder's components must exist; those below it are created when asked."""
        with contextlib.ExitStack() as stack:
            current = files.root(self.root)
            stack.callback(files.close, current)
            for name in self.components:
                current = stack.enter_context(_opened(current, name, create=False))
            for name in relative:
                current = stack.enter_context(_opened(current, name, create=create))
            yield current

    def read(self, relative: str) -> bytes:
        *parents, name = PurePosixPath(relative).parts
        with self._directory(tuple(parents), create=False) as parent:
            with _refusing(name):
                fd = files.open_at(parent, name)
            with os.fdopen(fd, "rb") as handle:
                return handle.read()

    def write(self, relative: str, data: bytes) -> None:
        """Write atomically, creating directories; a link at the name is replaced, not followed."""
        *parents, name = PurePosixPath(relative).parts
        with self._directory(tuple(parents), create=True) as parent:
            temporary = f".{secrets.token_hex(6)}.tmp"
            fd = files.create(parent, temporary, 0o666)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                files.rename(parent, temporary, name)
            except BaseException:
                files.unlink(parent, temporary)
                raise

    def create(self, name: str, data: bytes) -> None:
        """`write` in the folder itself, only where nothing is at the name; a link there stays."""
        with self._directory(()) as parent:
            try:
                files.status(parent, name)
            except FileNotFoundError:
                self.write(name, data)

    def empty(self, relative: str) -> None:
        """Delete a directory tree if present, refusing a link at the name; make its parents.

        The caller writes there next, into a folder that may not have them yet. Nothing below the
        name is followed either.
        """
        *parents, name = PurePosixPath(relative).parts
        with self._directory(tuple(parents), create=True) as parent:
            try:
                status = files.status(parent, name)
            except FileNotFoundError:
                return
            with _refusing(name):
                if fsutil.linked(status) or not stat.S_ISDIR(status.st_mode):
                    raise OSError(errno.ENOTDIR, os.strerror(errno.ENOTDIR))
            files.remove_tree(parent, name)


__all__ = ["RunFolder"]
