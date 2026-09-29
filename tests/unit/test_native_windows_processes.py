"""`native.processes` on Windows: a command runs in a job object, and stopping the job ends all
it started.

Each test first does what obelize would do without the job, in the same run, and shows that a
process escapes or keeps running, so a green run cannot pass over nothing.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from obelize.native import _win32, processes
from obelize.verify import runner
from platforms import PYTHON, alive, quoted, windows_only

pytestmark = windows_only("a job object; `test_native_win32.py` checks what it passes anywhere")

TOOLS = Path(__file__).resolve().parents[1] / "fixtures" / "verify" / "tools"

# `STATUS_CONTROL_C_EXIT`, which `GetExitCodeProcess` gives unsigned.
KILLED = 0xC000013A

# Generous: the assertions are that a process goes, and within a bound, not how fast.
GONE_S = 10.0

# Long enough for a Python that was let run to write its marker.
RUN_S = 3.0

# Starts a command in a job, or with a plain `Popen`, prints the command's pid and its child's,
# and sleeps until it is killed.
HOLDER = """
import os, subprocess, sys, time
from pathlib import Path
from obelize.native import processes

contained, argv = sys.argv[1] == "job", sys.argv[2:]
if contained:
    process = processes.spawn(argv, Path.cwd(), dict(os.environ))
    line = b""
    while not line.endswith(b"\\n"):
        line += processes.read(process.stdout, 4096, 0.1) or b""
else:
    process = subprocess.Popen(argv, stdout=subprocess.PIPE)
    line = process.stdout.readline()
print(process.pid, line.split()[1].decode(), flush=True)
time.sleep(60)
"""


def gone(pid: int) -> bool:
    """Whether `pid` has exited within `GONE_S`."""
    deadline = time.monotonic() + GONE_S
    while alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def survivors(*pids: int) -> list[int]:
    """Those of `pids` still running, each then killed. One that has gone is not touched, since
    Windows soon gives its pid to another process."""
    running = [pid for pid in pids if alive(pid)]
    for pid in running:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)  # `TerminateProcess` here
    return running


@pytest.fixture
def contained() -> Iterator[list[subprocess.Popen[bytes]]]:
    """What a test starts through `processes.spawn`, closed and reaped after it."""
    started: list[subprocess.Popen[bytes]] = []
    yield started
    for process in started:
        processes.close(process)
        with process:
            pass


def spawn(started: list[subprocess.Popen[bytes]], *argv: str, cwd: Path) -> subprocess.Popen[bytes]:
    process = processes.spawn(argv, cwd, dict(os.environ))
    started.append(process)
    return process


def first_line(process: subprocess.Popen[bytes]) -> list[str]:
    """The words of the first line a command printed, read as the runner reads."""
    stream = process.stdout
    assert stream is not None
    line = b""
    deadline = time.monotonic() + GONE_S
    while not line.endswith(b"\n"):
        assert time.monotonic() < deadline, f"no whole line came, only {line!r}"
        line += processes.read(stream, 4096, 0.1) or b""
    return line.decode().split()


def test_a_child_outlives_a_kill_of_the_command_but_not_the_stop_of_its_job(
    tmp_path: Path, contained: list[subprocess.Popen[bytes]]
) -> None:
    """Control: `Popen.kill`, which is `TerminateProcess` on the command alone."""
    plain = subprocess.Popen(
        [sys.executable, str(TOOLS / "orphan.py"), "60", str(tmp_path / "plain")],
        stdout=subprocess.PIPE,
    )
    with plain:
        assert plain.stdout is not None
        child = int(plain.stdout.readline().split()[1])
        plain.kill()
    assert survivors(child) == [child], "the child did not outlive a kill of the command alone"

    marker = tmp_path / "contained"
    process = spawn(
        contained, sys.executable, str(TOOLS / "orphan.py"), "60", str(marker), cwd=tmp_path
    )
    child = int(first_line(process)[1])
    processes.stop(process, 0)
    assert process.wait(timeout=GONE_S) == KILLED
    assert gone(child), "the child outlived the stop of the job it was started in"
    assert not marker.exists()


def test_a_command_that_ignores_every_request_is_gone_within_the_bound_after_a_stop(
    tmp_path: Path, contained: list[subprocess.Popen[bytes]]
) -> None:
    """Control: left alone for `RUN_S`, it and its child are still running, so the stop is what
    ends them. The child's marker would take 60 s to appear, so it is the child that is asked."""
    marker = tmp_path / "survived"
    process = spawn(
        contained, sys.executable, str(TOOLS / "stubborn.py"), "60", str(marker), cwd=tmp_path
    )
    armed, child = first_line(process)
    assert armed == "armed"
    with pytest.raises(subprocess.TimeoutExpired):
        process.wait(timeout=RUN_S)
    assert alive(int(child)), "the child was not running, so its end would show nothing"

    started = time.monotonic()
    processes.stop(process, 0)
    assert process.wait(timeout=GONE_S) == KILLED
    assert time.monotonic() - started < GONE_S
    assert gone(int(child)), "the child outlived the stop of the job it was started in"


def test_after_close_nothing_the_command_started_is_left(
    tmp_path: Path, contained: list[subprocess.Popen[bytes]]
) -> None:
    """Control: outside a job, letting go of the command's pipe leaves it and its child running."""
    plain = subprocess.Popen(
        [sys.executable, str(TOOLS / "orphan.py"), "60", str(tmp_path / "plain")],
        stdout=subprocess.PIPE,
    )
    assert plain.stdout is not None
    child = int(plain.stdout.readline().split()[1])
    plain.stdout.close()
    left = survivors(plain.pid, child)
    plain.wait()
    assert left == [plain.pid, child], "the command or its child ended without a job"

    marker = tmp_path / "contained"
    process = processes.spawn(
        [sys.executable, str(TOOLS / "orphan.py"), "60", str(marker)], tmp_path, dict(os.environ)
    )
    with process:
        try:
            child = int(first_line(process)[1])
        finally:
            processes.close(process)
        assert gone(process.pid), "the command outlived the close of its job"
        assert gone(child), "the child outlived the close of its job"
    assert not marker.exists()


def orphaned_by_a_killed_holder(tmp_path: Path, how: str) -> tuple[int, int]:
    """The pids of a command a holder started `how`, and of its child, once the holder is
    killed as a crashed obelize would be."""
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            HOLDER,
            how,
            sys.executable,
            str(TOOLS / "orphan.py"),
            "60",
            str(tmp_path / f"{how}.survived"),
        ],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
    )
    with holder:
        assert holder.stdout is not None
        command, child = (int(pid) for pid in holder.stdout.readline().split())
        holder.kill()
    return command, child


def test_what_a_dead_obelize_started_dies_with_it_through_its_job(tmp_path: Path) -> None:
    """`KILL_ON_JOB_CLOSE`: the kernel closes a dead process's handles, the job's last one too.

    Control: started with a plain `Popen`, the command and its child outlive the killed holder.
    """
    command, child = orphaned_by_a_killed_holder(tmp_path, "plain")
    assert survivors(command, child) == [command, child], "the control ended with its holder"

    command, child = orphaned_by_a_killed_holder(tmp_path, "job")
    assert gone(command), "the command outlived the obelize that started it"
    assert gone(child), "the child outlived the obelize whose command started it"
    assert not (tmp_path / "job.survived").exists()


def test_a_command_its_job_cannot_hold_never_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assignment is refused only after `RUN_S`, which a command already running would use.

    Control: started as a plain `Popen` starts it, the same command has run by then.
    """
    marker = tmp_path / "ran"
    script = tmp_path / "mark.py"
    script.write_text("import sys\nopen(sys.argv[1], 'w').close()\n", encoding="utf-8")
    plain = subprocess.Popen([sys.executable, str(script), str(marker)])
    time.sleep(RUN_S)
    plain.kill()
    plain.wait()
    assert marker.exists(), "the control did not run within the time the refusal takes"
    marker.unlink()

    started: list[subprocess.Popen[bytes]] = []

    class Recorded(subprocess.Popen[bytes]):
        def __init__(self, *arguments: Any, **keywords: Any) -> None:
            super().__init__(*arguments, **keywords)
            started.append(self)

    def refused(job: int, process: int) -> None:
        time.sleep(RUN_S)
        raise OSError("AssignProcessToJobObject failed with Windows error 5")

    monkeypatch.setattr(subprocess, "Popen", Recorded)
    monkeypatch.setattr(_win32, "assign", refused)
    result = runner.execute(
        tmp_path,
        runner.Command.of(f"{PYTHON} {quoted(script)} {quoted(marker)}", "cli"),
        timeout_s=30,
        environ=dict(os.environ),
    )
    assert (result.status, result.reason) == ("inconclusive", "command_not_executable")
    assert "could not be contained" in result.output
    assert not marker.exists()
    (process,) = started
    assert process.returncode is not None
    assert not alive(process.pid)


def test_a_command_interrupted_before_its_job_holds_it_is_killed_and_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ctrl+C before the assignment: the job is closed, and the command, started suspended,
    would wait forever for a resume.

    Control: with nothing killing it on the way out, the same interrupt leaves it there.
    """
    started: list[subprocess.Popen[bytes]] = []

    class Recorded(subprocess.Popen[bytes]):
        def __init__(self, *arguments: Any, **keywords: Any) -> None:
            super().__init__(*arguments, **keywords)
            started.append(self)

    def interrupted(job: int, process: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, "Popen", Recorded)
    monkeypatch.setattr(_win32, "assign", interrupted)
    argv = [sys.executable, "-c", "pass"]
    with monkeypatch.context() as unprotected:
        unprotected.setattr(_win32, "killed_on_error", lambda process: contextlib.nullcontext())
        with pytest.raises(KeyboardInterrupt):
            processes.spawn(argv, tmp_path, dict(os.environ))
    (left,) = started
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            left.wait(timeout=RUN_S)
    finally:
        with left:
            left.kill()

    with pytest.raises(KeyboardInterrupt):
        processes.spawn(argv, tmp_path, dict(os.environ))
    _, process = started
    assert process.returncode is not None, "the command was left suspended"
    assert not alive(process.pid)


def test_a_command_whose_job_cannot_be_made_is_never_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: with its job made, the same command is started, and the count sees it."""
    started: list[subprocess.Popen[bytes]] = []

    class Recorded(subprocess.Popen[bytes]):
        def __init__(self, *arguments: Any, **keywords: Any) -> None:
            super().__init__(*arguments, **keywords)
            started.append(self)

    def unmade() -> int:
        raise OSError("CreateJobObjectW failed with Windows error 1455")

    monkeypatch.setattr(subprocess, "Popen", Recorded)
    command = runner.Command.of(f"{PYTHON} -c pass", "cli")
    runner.execute(tmp_path, command, timeout_s=30, environ=dict(os.environ))
    assert len(started) == 1, "the control did not start the command"

    monkeypatch.setattr(_win32, "new_job", unmade)
    result = runner.execute(tmp_path, command, timeout_s=30, environ=dict(os.environ))
    assert (result.status, result.reason) == ("inconclusive", "command_not_executable")
    assert "CreateJobObjectW failed" in result.output
    assert len(started) == 1
