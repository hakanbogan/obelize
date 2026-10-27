"""The maintained tools an `external_fixer` runs: a closed registry, and one run over one file.

A tool is found among the absolute entries of the person's `PATH`, never in the repository, and
never installed: obelize installs nothing. It is run as the agent is (ADR-003): an argv list and no
shell, a few environment variables, an empty directory, a deadline, and a size on what goes in and
comes out, and in a group of its own (a job on Windows) that ends with the run, so what it starts
cannot outlive it or keep the read waiting. Only a release the registry lists runs, since what a
rule fixes changes between releases (ADR-074).
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from obelize.native import processes
from obelize.transforms.base import BailError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from obelize.models import FixerId

TIMEOUT_S: Final = 60.0
# The most a tool is given, and the most it may print: no more than this is read.
LIMIT: Final = 1 << 22
# Seconds a pipe is read for after the tool has exited, since what it started may hold it.
DRAIN_S: Final = 1.0
_CHUNK: Final = 1 << 16
_POLL_S: Final = 0.05
_RELEASE: Final = re.compile(r"\d+\.\d+\.\d+")
# What a tool needs to start: none of its own settings (`RUFF_*` changes what it prints), no token.
_KEPT: Final = frozenset(
    {"PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
)


@dataclass(frozen=True, slots=True)
class Fixer:
    """One tool run one way. `argv` follows the program and reads a file on stdin, writing it on
    stdout; `{name}` is the file's name. `releases` is a PEP 440 range of which every release was
    run over the bundled pack's fixtures and wrote the same bytes, and `install` what a person runs
    to have one."""

    tool: str
    releases: str
    argv: tuple[str, ...]
    install: str
    probe: tuple[str, ...] = ("--version",)


@dataclass(frozen=True, slots=True)
class Ran:
    """What a tool printed for a file, and the release that printed it."""

    version: str
    output: bytes


def _ruff(rule: str) -> Fixer:
    """`ruff check --fix-only` for one rule, with no configuration of the repository or the
    person (`--isolated`); its leftover findings are neither printed nor an exit code."""
    argv = ("check", "--isolated", "--select", rule, "--fix-only", "--stdin-filename={name}", "-")
    return Fixer("ruff", ">=0.6.2,<=0.17.3", argv, "ruff==0.17.3")


# Keyed by `models.FixerId`, which holds the same set (tested).
FIXERS: Final[dict[FixerId, Fixer]] = {"ruff:NPY201": _ruff("NPY201")}


def environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The variables a tool starts with."""
    return {name: value for name, value in environ.items() if name in _KEPT}


def run(fixer: FixerId, name: str, data: bytes, environ: Mapping[str, str] = os.environ) -> Ran:
    """The tool's output for the file `name`, or `BailError` with the code that says why none."""
    if len(data) > LIMIT:
        raise BailError("external_tool_size_limit")
    program, version = ready(fixer, environ)
    argv = [program, *(word.replace("{name}", name) for word in FIXERS[fixer].argv)]
    status, printed = _spawn(argv, data, environ)
    if status != 0:
        raise BailError("external_tool_failed")
    return Ran(version, printed)


def ready(fixer: FixerId, environ: Mapping[str, str] = os.environ) -> tuple[str, str]:
    """Where the tool is and the release it is, or `BailError` if it is not here or not accepted."""
    spec = FIXERS[fixer]
    path = os.pathsep.join(
        entry for entry in environ.get("PATH", "").split(os.pathsep) if os.path.isabs(entry)
    )
    program = processes.locate(spec.tool, {"PATH": path})
    if program is None:
        raise BailError("external_tool_missing")
    stat = os.stat(program)
    version = _release(
        program,
        spec.probe,
        tuple(sorted(environment(environ).items())),
        stat.st_mtime_ns,
        stat.st_size,
    )
    if not _RELEASE.fullmatch(version) or Version(version) not in SpecifierSet(spec.releases):
        raise BailError("external_tool_version_unsupported")
    return program, version


def problem(fixer: FixerId, environ: Mapping[str, str] = os.environ) -> str | None:
    """Why the tool cannot run here, with the command that fixes it, or `None`."""
    try:
        ready(fixer, environ)
    except BailError as bail:
        return f"{fixer}: {bail.reason}; install it with `uv tool install {FIXERS[fixer].install}`"
    return None


@functools.cache
def _release(
    program: str,
    probe: tuple[str, ...],
    environ: tuple[tuple[str, str], ...],
    modified: int,
    size: int,
) -> str:
    """The last word of the first line the tool prints for `probe` (`ruff 0.16.8`). The file's
    time and size are in the key, so a tool that was replaced is asked again."""
    status, printed = _spawn([program, *probe], b"", dict(environ))
    words = printed.decode("utf-8", "replace").split("\n", 1)[0].split()
    if status != 0 or not words:
        raise BailError("external_tool_failed")
    return words[-1]


def _spawn(argv: list[str], data: bytes, environ: Mapping[str, str]) -> tuple[int, bytes]:
    """The tool's exit status and the first `LIMIT` + 1 bytes it printed on stdout.

    It reads `data` from a file given as its stdin (there is no pipe to feed), its stderr is
    dropped, and `processes.close` ends its whole group however the run ended.
    """
    with (
        tempfile.TemporaryDirectory(prefix="obelize-fixer-", ignore_cleanup_errors=True) as empty,
        tempfile.TemporaryFile() as stdin,
    ):
        stdin.write(data)
        stdin.seek(0)
        try:
            process = processes.spawn(
                argv, Path(empty), environment(environ), stdin=stdin, stderr=subprocess.DEVNULL
            )
        except OSError as error:
            raise BailError("external_tool_failed") from error
        try:
            return _drain(process)
        finally:
            processes.close(process)
            process.wait()


def _drain(process: subprocess.Popen[bytes]) -> tuple[int, bytes]:
    """Read stdout to its end, the deadline or `LIMIT` + 1 bytes, then wait for the exit status.

    After the tool has exited a pipe something else holds is read for `DRAIN_S` more, and so ended.
    """
    stream = process.stdout
    if stream is None:  # pragma: no cover - `spawn` opens a pipe, so it never is
        raise RuntimeError("the process was started without a pipe")
    deadline = time.monotonic() + TIMEOUT_S
    printed = bytearray()
    exited: float | None = None
    try:
        while len(printed) <= LIMIT:
            now = time.monotonic()
            if exited is None and process.poll() is not None:
                exited = now
            if now >= deadline:
                raise subprocess.TimeoutExpired(process.args, TIMEOUT_S)
            if exited is not None and now >= exited + DRAIN_S:
                break
            chunk = processes.read(stream, _CHUNK, min(deadline - now, _POLL_S))
            if chunk is None:
                continue
            if not chunk:
                break
            printed += chunk
        if len(printed) > LIMIT:
            raise BailError("external_tool_size_limit")
        status = process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        raise BailError("external_tool_timeout") from error
    return status, bytes(printed)


__all__ = ["FIXERS", "LIMIT", "TIMEOUT_S", "Fixer", "Ran", "environment", "problem", "ready", "run"]
