"""Process control on Windows: a command runs in a job object, so one call ends all it started.

obelize looks each program up itself (`windows_programs`).
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO

from obelize.native import _win32, windows_programs
from obelize.native.windows_programs import command_problem
from obelize.native.windows_programs import name as program_name

assert sys.platform == "win32"  # noqa: S101 - `mypy` for another platform reads no further

# `ProcessPoolExecutor` waits on its workers with `WaitForMultipleObjects`, which takes 64
# handles, three of them its own; above this it raises `ValueError`.
WORKER_LIMIT: int | None = 61

# Seconds an empty pipe is left before it is read again.
POLL_S = 0.01

# Seconds a terminated job is given to empty, since its processes may still be exiting.
EMPTIED_S = 5.0

# The job of each running command, by the pid of the process `spawn` started.
_JOBS: dict[int, int] = {}


def spawn(argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> subprocess.Popen[bytes]:
    """As on POSIX, but the command starts suspended and runs only once its job holds it, so
    whatever it starts is in the job too. If that fails or is interrupted it is killed before
    it ran."""
    executable = resolve(argv[0], env, cwd)
    job = _win32.new_job()
    with _win32.closed_on_error(job):
        process = subprocess.Popen(
            argv,
            executable=executable,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=_win32.CREATE_NEW_PROCESS_GROUP | _win32.CREATE_SUSPENDED,
        )
        with _win32.killed_on_error(process):
            try:
                _contain(process, job)
            except OSError as error:
                raise OSError(f"it could not be contained, so it did not run: {error}") from error
    _JOBS[process.pid] = job
    return process


def _contain(process: subprocess.Popen[bytes], job: int) -> None:
    stream = process.stdout
    assert stream is not None  # noqa: S101 - `stdout=PIPE` opened it
    os.set_blocking(stream.fileno(), False)
    handle = _win32.open_process(
        process.pid,
        _win32.PROCESS_SET_QUOTA | _win32.PROCESS_TERMINATE | _win32.PROCESS_SUSPEND_RESUME,
    )
    try:
        _win32.assign(job, handle)
        _win32.resume(handle)
    finally:
        _win32.close(handle)


def read(stream: IO[bytes], size: int, timeout: float) -> bytes | None:
    """Up to `size` bytes, `b""` at EOF, or `None` when nothing has arrived.

    `select` takes no pipe here, so `spawn` made this one non-blocking, and an empty one is left
    for up to `timeout` seconds.
    """
    try:
        return os.read(stream.fileno(), size)
    except BlockingIOError:
        time.sleep(min(timeout, POLL_S))
        return None


def stop(process: subprocess.Popen[bytes], grace: float) -> None:
    """Terminate the command's whole job at once.

    No process in a job can ignore that, so there is no `grace` to give first.
    """
    _terminate(_JOBS[process.pid])


def end(group: int) -> None:
    """Terminate what an exited command left in its job, named by the pid `spawn` started."""
    _terminate(_JOBS[group])


def close(process: subprocess.Popen[bytes]) -> None:
    """Terminate the command's job and close it.

    Terminating covers a process that duplicated the job's handle. When obelize is interrupted
    or dies, the handle closes anyway, and `KILL_ON_JOB_CLOSE` ends the rest.
    """
    job = _JOBS.pop(process.pid)
    try:
        _terminate(job)
    finally:
        _win32.close(job)


def _terminate(job: int) -> None:
    _win32.terminate(job, _win32.STATUS_CONTROL_C_EXIT)
    deadline = time.monotonic() + EMPTIED_S
    while _win32.active_processes(job) and time.monotonic() < deadline:
        time.sleep(POLL_S)


def resolve(program: str, env: Mapping[str, str], cwd: Path) -> str:
    """The file to run for `program`, given as `executable` so `CreateProcess` searches nothing."""
    return windows_programs.search(program, env.get("PATH", ""), str(cwd), os.path.isfile)


def locate(program: str, env: Mapping[str, str]) -> str | None:
    """Where the command's `PATH` finds a bare `program`; `None` for one named by its path."""
    if not windows_programs.bare(program):
        return None
    try:
        return resolve(program, env, Path())
    except OSError:
        return None


def git() -> str:
    """git on obelize's own `PATH`, looked up once per `PATH`; `FileNotFoundError` if absent."""
    return _git(os.environ.get("PATH", ""))


@functools.cache
def _git(path: str) -> str:
    return windows_programs.search("git", path, "", os.path.isfile)


__all__ = [
    "WORKER_LIMIT",
    "close",
    "command_problem",
    "end",
    "git",
    "locate",
    "program_name",
    "read",
    "resolve",
    "spawn",
    "stop",
]
