"""What a test does differently on Windows: privilege, quoting, denial, programs, links, liveness.

Each helper keeps the POSIX calls the suite made before, so a POSIX run tests what it did. The
`*_as_on_windows` helpers give any system Windows' text layer, so its effect is tested here too.
"""

from __future__ import annotations

import contextlib
import errno
import functools
import io
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

if sys.platform == "win32":
    import _winapi
    import msvcrt

    # A deny entry binds an elevated administrator too; only backup privilege skips it.
    AS_ROOT = False
else:
    AS_ROOT = os.geteuid() == 0

# Command text is split by `shlex`, which drops the backslashes of an unquoted Windows path.
PYTHON = shlex.quote(sys.executable)


def quoted(path: Path) -> str:
    return shlex.quote(str(path))


def copied(argument: Path | str) -> str:
    """`argument` as a command printed for the user to copy spells it: cmd.exe reads no single
    quote, so on Windows it is quoted as `subprocess.list2cmdline` quotes it."""
    if sys.platform == "win32":
        spelled = subprocess.list2cmdline([str(argument)])
    else:
        spelled = shlex.quote(str(argument))
    return spelled


def posix_only(reason: str) -> pytest.MarkDecorator:
    """Skip on Windows; `reason` names what the test rests on and what tests Windows instead."""
    return pytest.mark.skipif(sys.platform == "win32", reason=reason)


def windows_only(reason: str) -> pytest.MarkDecorator:
    """Skip elsewhere; `reason` names what the test shows on Windows and what shows it here."""
    return pytest.mark.skipif(sys.platform != "win32", reason=reason)


SIGNALS = posix_only("POSIX signals and process groups; the job object tests cover Windows")
MODE_BITS = posix_only("POSIX mode bits; the access control tests cover Windows")
SHEBANG = posix_only("a '#!' script is not a Windows program; the lookup tests cover Windows")
BENCH = posix_only("bench builds POSIX virtual environments and is not measured on Windows")


def text_files_as_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Path.write_text` ending each line with CRLF unless told otherwise, as Windows does."""
    write = Path.write_text

    def crlf(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        return write(self, data, encoding, errors, "\r\n" if newline is None else newline)

    monkeypatch.setattr(Path, "write_text", crlf)


def stdout_as_on_windows(monkeypatch: pytest.MonkeyPatch) -> io.BytesIO:
    """A redirected Windows stdout, cp1252 with CRLF line ends; returns the bytes that reach it."""
    reached = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(reached, encoding="cp1252", newline="\r\n"))
    return reached


def reports_held_as_on_windows(monkeypatch: pytest.MonkeyPatch, temporary: Path) -> None:
    """A junit report cannot be deleted, as on Windows while a killed test runner still holds
    it; temporary folders are made in `temporary`, where what stays behind can be seen."""
    temporary.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temporary))
    unlink = os.unlink

    def held(path: str | os.PathLike[str], *, dir_fd: int | None = None) -> None:
        if os.fspath(path).endswith(".junit.xml"):
            raise PermissionError(errno.EACCES, "The file is open in another process", path)
        unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", held)


@contextlib.contextmanager
def deny(path: Path, *, writes_only: bool = False) -> Iterator[None]:
    """Take the current user's access to `path` away, or only the right to add names to it.

    `chmod` on Windows toggles the read-only flag, which a directory ignores, so there a deny
    entry for the user's SID does it; a full denial of a directory reaches what it holds. A name
    Windows allows to be deleted stays deletable, where POSIX asks the directory.
    """
    if sys.platform == "win32":
        if writes_only:
            rights, targets = "(WD,AD)", [path]
        else:
            # Under OWNER RIGHTS, F denies WRITE_DAC; (OI)(CI) propagates through a folder it hid.
            rights = "(RD,WD,AD,REA,WEA,X,DC,WA,D)"
            held = [Path(top, name) for top, dirs, names in os.walk(path) for name in dirs + names]
            targets = [*sorted(held, key=lambda each: len(each.parts), reverse=True), path]
        denied: list[Path] = []
        try:
            for target in targets:
                _icacls(target, "/deny", f"*{_sid()}:{rights}")
                denied.append(target)
            yield
        finally:
            for target in reversed(denied):
                _icacls(target, "/remove:d", f"*{_sid()}")
    else:
        mode = stat.S_IMODE(path.stat().st_mode)
        path.chmod(0o500 if writes_only else 0)
        try:
            yield
        finally:
            path.chmod(mode)


def _icacls(path: Path, *arguments: str) -> None:
    subprocess.run(["icacls", str(path), *arguments], check=True, capture_output=True)


@functools.cache
def _sid() -> str:
    """The user's SID: `icacls` takes it whatever language the account names are in."""
    listed = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"], check=True, capture_output=True
    ).stdout
    return listed.decode("ascii", "replace").rsplit(",", 1)[1].strip().strip('"')


def program(path: Path, *, passes: bool) -> Path:
    """A program at `path` that exits 0, or non-zero unless `passes`; returns where it is.

    A `#!` script is no Windows program, so there `path.exe` is a copy of a System32 one:
    `hostname` exits 0 and `findstr`, given no pattern, exits 2.
    """
    if sys.platform == "win32":
        made = path.with_name(f"{path.name}.exe")
        source = "hostname.exe" if passes else "findstr.exe"
        shutil.copyfile(Path(os.environ["SYSTEMROOT"], "System32", source), made)
    else:
        made = path
        made.write_bytes(f"#!/bin/sh\nexit {0 if passes else 1}\n".encode())
        made.chmod(0o755)
    return made


def link(path: Path, target: Path | str) -> None:
    """A symbolic link; Windows makes a directory link only when told the target is one."""
    path.symlink_to(target, target_is_directory=(path.parent / target).is_dir())


def junction(path: Path, target: Path) -> None:
    """The directory link any Windows user can make, which `is_symlink` misses; POSIX symlinks."""
    if sys.platform == "win32":
        _winapi.CreateJunction(str(target), str(path))
    else:
        path.symlink_to(target, target_is_directory=True)


@contextlib.contextmanager
def held(path: Path) -> Iterator[int]:
    """`path` open for reading as an editor or an indexer holds it; yields its descriptor.

    Windows' `open` would keep a rename out, so there the handle shares read, write and delete,
    as those programs' handles do.
    """
    if sys.platform == "win32":
        handle = _winapi.CreateFile(
            str(path), _winapi.GENERIC_READ, 0x7, 0, _winapi.OPEN_EXISTING, 0, 0
        )
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    else:
        descriptor = os.open(path, os.O_RDONLY)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def alive(pid: int) -> bool:
    """Whether `pid` has not exited; `os.kill(pid, 0)` on Windows would terminate it."""
    if sys.platform == "win32":
        try:
            handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, pid)
        except OSError:
            return False
        try:
            return _winapi.WaitForSingleObject(handle, 0) == _winapi.WAIT_TIMEOUT
        finally:
            _winapi.CloseHandle(handle)
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
