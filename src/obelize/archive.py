"""Unpack the source of a release that came from a network, and nothing else.

An archive is data from a stranger. It is never built, installed or run: only files that are source
(`.py`, `.pyi`) or describe a distribution (`METADATA`, `RECORD`, `top_level.txt`) are written, each
under a name checked on every system, to a directory that is new and the person's alone. A name that
leaves it, a link, a device, a name Windows would read as another, two names that are one on a case
folding system, a file or an archive past its size and a count past its limit all stop the unpacking
with an `ArchiveError`, and what was written stays with the directory the caller removes.
"""

from __future__ import annotations

import io
import posixpath
import stat
import tarfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from obelize.native.windows_names import reserved

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# What one file may hold, what all of them may, and how many there may be.
FILE_BYTES: Final = 20 << 20
TOTAL_BYTES: Final = 256 << 20
FILE_COUNT: Final = 50_000
# How many bytes may come out of one compressed byte before the archive is a bomb.
RATIO: Final = 200

_SUFFIXES: Final = (".py", ".pyi")
_DESCRIBING: Final = ("METADATA", "RECORD", "top_level.txt", "entry_points.txt")


class ArchiveError(Exception):
    """An archive that was refused, and why, in words for the person."""


@dataclass(frozen=True, slots=True)
class Unpacked:
    """What was written: where, how many files, how many bytes, and how many were left out."""

    root: Path
    files: int
    size: int
    left: int


def unpack(data: bytes, filename: str, into: Path) -> Unpacked:
    """Unpack the wheel or source distribution `data`, called `filename`, into the new directory
    `into`. The top directory of a source distribution (`name-1.0/`) is dropped."""
    name = filename.lower()
    if name.endswith((".whl", ".zip")):
        members = _zipped(data)
        strip = not name.endswith(".whl")
    elif name.endswith((".tar.gz", ".tgz", ".tar")):
        members = _tarred(data)
        strip = True
    else:
        raise ArchiveError(f"{filename} is neither a wheel nor a source distribution")
    into.mkdir(mode=0o700, parents=True)
    return _write(members, into, strip=strip)


@dataclass(frozen=True, slots=True)
class _Entry:
    """One member as the archive declares it; its bytes are read only if it is wanted."""

    name: str
    directory: bool
    size: int
    packed: int
    read: Callable[[], bytes]


def _zipped(data: bytes) -> Iterator[_Entry]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ArchiveError(f"not a zip archive: {error}") from error
    with archive:
        for info in archive.infolist():
            # A writer that sets no type bits (Python's `writestr`) means a regular file.
            kind = stat.S_IFMT(info.external_attr >> 16)
            if not info.is_dir() and kind not in (0, stat.S_IFREG):
                raise ArchiveError(f"{info.filename} is a link or a device, not a file")

            def read(info: zipfile.ZipInfo = info, archive: zipfile.ZipFile = archive) -> bytes:
                try:
                    with archive.open(info) as handle:
                        return handle.read(FILE_BYTES + 1)
                except (
                    zipfile.BadZipFile,
                    NotImplementedError,
                    RuntimeError,
                    EOFError,
                    zlib.error,
                ) as error:
                    raise ArchiveError(f"{info.filename} cannot be read: {error}") from error

            yield _Entry(
                info.filename, info.is_dir(), info.file_size, max(info.compress_size, 1), read
            )


def _tarred(data: bytes) -> Iterator[_Entry]:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")  # noqa: SIM115
    except tarfile.TarError as error:
        raise ArchiveError(f"not a tar archive: {error}") from error
    with archive:
        for member in archive:
            if not member.isdir() and not member.isreg():
                raise ArchiveError(f"{member.name} is a link or a device, not a file")

            def read(member: tarfile.TarInfo = member, archive: tarfile.TarFile = archive) -> bytes:
                handle = archive.extractfile(member)
                assert handle is not None  # noqa: S101 - a regular member always has content
                try:
                    return handle.read(FILE_BYTES + 1)
                except (tarfile.TarError, EOFError, zlib.error) as error:
                    raise ArchiveError(f"{member.name} cannot be read: {error}") from error

            yield _Entry(member.name, member.isdir(), member.size, max(member.size, 1), read)


def _write(members: Iterator[_Entry], into: Path, *, strip: bool) -> Unpacked:
    seen: set[str] = set()
    files = size = left = 0
    for entry in members:
        name = _checked(entry.name, strip=strip)
        if name is None or entry.directory:
            continue
        if entry.size > FILE_BYTES:
            raise ArchiveError(f"{entry.name} holds more than {FILE_BYTES} bytes")
        if entry.size // entry.packed > RATIO and entry.size > (1 << 20):
            raise ArchiveError(f"{entry.name} unpacks to far more than it holds: an archive bomb")
        folded = name.casefold()
        if folded in seen:
            raise ArchiveError(
                f"{entry.name} and another entry are one name on a system that ignores case"
            )
        seen.add(folded)
        files += 1
        if files > FILE_COUNT:
            raise ArchiveError(f"the archive holds more than {FILE_COUNT} files")
        if not _wanted(name):
            left += 1
            continue
        # Bounded by the declared size, which was checked above: neither format reads past it.
        content = entry.read()
        size += len(content)
        if size > TOTAL_BYTES:
            raise ArchiveError(f"the archive unpacks past {TOTAL_BYTES} bytes")
        target = into / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.write_bytes(content)
    return Unpacked(into, files - left, size, left)


def _checked(raw: str, *, strip: bool) -> str | None:
    """The name to write under, or `None` for the top directory of a source distribution.

    A name that could leave the directory, or mean another file on some system, is an error even if
    nothing here would have written it: a stranger's archive is not given the benefit of the doubt.
    """
    if not raw or "\x00" in raw or "\\" in raw or raw.startswith("/") or ":" in raw:
        raise ArchiveError(f"{raw!r} is not a name inside an archive")
    path = PurePosixPath(posixpath.normpath(raw))
    if ".." in path.parts:
        raise ArchiveError(f"{raw} leaves the directory it is unpacked into")
    parts = path.parts[1:] if strip else path.parts
    if not parts:
        return None
    name = "/".join(parts)
    if reserved(name):
        raise ArchiveError(f"{raw} is a name some system reads as another file")
    return name


def _wanted(name: str) -> bool:
    final = name.rpartition("/")[2]
    return name.endswith(_SUFFIXES) or (
        final in _DESCRIBING and (".dist-info/" in name or "/" not in name or ".egg-info/" in name)
    )


__all__ = ["ArchiveError", "Unpacked", "unpack"]
