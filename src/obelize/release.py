"""Read one release of a project: download its file, check it against the index's hash, unpack the
source of it. Nothing is built, installed or run (`obelize.archive`)."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

from obelize.archive import Unpacked, unpack
from obelize.net import Cache, Fetcher

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from obelize.index import File

# The most a wheel or source distribution may hold: the large scientific wheels are under it.
FILE_BYTES: Final = 128 << 20


class ReleaseError(Exception):
    """A file whose bytes are not the ones the index promised."""


def download(fetcher: Fetcher, file: File) -> bytes:
    """The bytes of `file`, kept by their hash, and checked against it every time they are read:
    a cache entry is not believed on its name."""
    key = Cache.key("file", file.sha256)
    data = fetcher.get(
        file.url, accept="application/octet-stream", max_bytes=FILE_BYTES, ttl_s=None, key=key
    )
    if hashlib.sha256(data).hexdigest() != file.sha256:
        raise ReleaseError(
            f"{file.filename} does not have the sha256 the index gave for it, so it was not used"
        )
    return data


@contextmanager
def read(fetcher: Fetcher, file: File) -> Iterator[Unpacked]:
    """The source of `file` in a directory that exists for the length of the `with`."""
    data = download(fetcher, file)
    scratch = tempfile.mkdtemp(prefix="obelize-release-")
    try:
        yield unpack(data, file.filename, _fresh(scratch))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _fresh(scratch: str) -> Path:
    from pathlib import Path

    return Path(scratch) / "release"


__all__ = ["FILE_BYTES", "ReleaseError", "download", "read"]
