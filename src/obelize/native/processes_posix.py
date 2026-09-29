"""Process control on POSIX: a command gets its own session, so one signal reaches its group."""

from __future__ import annotations

import contextlib
import os
import select
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import IO

assert sys.platform != "win32"  # noqa: S101 - `mypy --platform win32` reads no further

# `ProcessPoolExecutor` takes any number of workers here.
WORKER_LIMIT: int | None = None


def spawn(argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> subprocess.Popen[bytes]:
    """One pipe carries stdout and stderr, stdin is at EOF, and `stop` reaches all it starts."""
    return subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )


def read(stream: IO[bytes], size: int, timeout: float) -> bytes | None:
    """Up to `size` bytes, `b""` at EOF, or `None` when nothing arrives within `timeout` seconds."""
    if not select.select([stream], [], [], timeout)[0]:
        return None
    return os.read(stream.fileno(), size)


def stop(process: subprocess.Popen[bytes], grace: float) -> None:
    """SIGTERM the process group, then SIGKILL after `grace` seconds.

    The group, not the process: a child holding the pipe would block the read and keep running.
    """
    try:
        group = os.getpgid(process.pid)
        os.killpg(group, signal.SIGTERM)
    except OSError:  # `ProcessLookupError` included: it exited between the two calls
        return
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(group, signal.SIGKILL)


def end(group: int) -> None:
    """SIGKILL what an exited command left in its group, named by pid since the leader is reaped."""
    with contextlib.suppress(OSError):
        os.killpg(group, signal.SIGKILL)


def close(process: subprocess.Popen[bytes]) -> None:
    """Nothing to release: a process group is no handle, and `end` kills what the command left."""


def git() -> str:
    """`Popen` looks it up on `PATH`, as a shell does."""
    return "git"


def locate(program: str, env: Mapping[str, str]) -> str | None:
    """Where the command's `PATH` finds a bare `program`; `None` for one named by its path."""
    if os.sep in program:
        return None
    return shutil.which(program, path=env.get("PATH", os.defpath))


def program_name(program: str) -> str:
    return PurePosixPath(program).name


def command_problem(text: str) -> str | None:
    """`None`: every command reads here as `shlex` splits it."""
    return None


__all__ = [
    "WORKER_LIMIT",
    "close",
    "command_problem",
    "end",
    "git",
    "locate",
    "program_name",
    "read",
    "spawn",
    "stop",
]
