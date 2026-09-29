"""`tests/platforms.py`: each helper does on this platform what the tests using it assume."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from platforms import AS_ROOT, PYTHON, alive, deny, held, junction, link, program, quoted


def test_the_interpreter_survives_the_split_a_command_goes_through() -> None:
    assert shlex.split(f"{PYTHON} -c pass") == [sys.executable, "-c", "pass"]


def test_a_quoted_path_is_one_word_whatever_it_holds(tmp_path: Path) -> None:
    awkward = tmp_path / "a b" / "c'd"
    assert shlex.split(f"tool {quoted(awkward)}") == ["tool", str(awkward)]


def test_a_denied_file_is_unreadable_unless_as_root_and_is_given_back(tmp_path: Path) -> None:
    """Every permission test skips on `AS_ROOT`, so it is held to what a denial does here."""
    secret = tmp_path / "secret.py"
    secret.write_bytes(b"x = 1\n")
    with deny(secret):
        try:
            secret.read_bytes()
        except PermissionError:
            readable = False
        else:
            readable = True
    assert readable is AS_ROOT
    assert secret.read_bytes() == b"x = 1\n"


@pytest.mark.skipif(AS_ROOT, reason="root reads a directory it may not")
def test_a_denied_directory_hides_what_it_holds_at_any_depth_and_gives_it_back(
    tmp_path: Path,
) -> None:
    """Windows skips traverse checks, so there each name below is denied, and must be restored."""
    (tmp_path / "sealed" / "inner").mkdir(parents=True)
    (tmp_path / "sealed" / "hidden.py").write_bytes(b"x = 1\n")
    (tmp_path / "sealed" / "inner" / "deep.py").write_bytes(b"y = 2\n")
    with deny(tmp_path / "sealed"):
        with pytest.raises(PermissionError):
            (tmp_path / "sealed" / "hidden.py").read_bytes()
        with pytest.raises(PermissionError):
            (tmp_path / "sealed" / "inner" / "deep.py").read_bytes()
        with pytest.raises(PermissionError):
            list((tmp_path / "sealed").iterdir())
    assert (tmp_path / "sealed" / "hidden.py").read_bytes() == b"x = 1\n"
    assert (tmp_path / "sealed" / "inner" / "deep.py").read_bytes() == b"y = 2\n"
    shutil.rmtree(tmp_path / "sealed")
    assert not (tmp_path / "sealed").exists()


@pytest.mark.skipif(AS_ROOT, reason="root writes into a directory it may not")
def test_a_directory_denied_writes_is_read_but_takes_no_new_name(tmp_path: Path) -> None:
    (tmp_path / "locked").mkdir()
    (tmp_path / "locked" / "kept.py").write_bytes(b"x = 1\n")
    with deny(tmp_path / "locked", writes_only=True):
        assert (tmp_path / "locked" / "kept.py").read_bytes() == b"x = 1\n"
        with pytest.raises(PermissionError):
            (tmp_path / "locked" / "new.py").write_bytes(b"y = 2\n")
        with pytest.raises(PermissionError):
            (tmp_path / "locked" / "new").mkdir()
    (tmp_path / "locked" / "new.py").write_bytes(b"y = 2\n")


def test_a_link_to_a_directory_is_walked_through(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "inner.py").write_bytes(b"x = 1\n")
    link(tmp_path / "linked", tmp_path / "real")
    assert (tmp_path / "linked").is_symlink()
    assert (tmp_path / "linked" / "inner.py").read_bytes() == b"x = 1\n"


def test_a_junction_reaches_its_directory(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "inner.py").write_bytes(b"x = 1\n")
    junction(tmp_path / "joined", tmp_path / "real")
    assert (tmp_path / "joined").is_symlink() or (tmp_path / "joined").is_junction()
    assert (tmp_path / "joined" / "inner.py").read_bytes() == b"x = 1\n"


def test_a_held_file_can_be_renamed_and_still_reads_what_was_opened(tmp_path: Path) -> None:
    """Windows' `open` would refuse the rename; a holder that shares delete lets it happen."""
    (tmp_path / "app.py").write_bytes(b"x = 1\n")
    with held(tmp_path / "app.py") as descriptor:
        (tmp_path / "app.py").rename(tmp_path / "moved.py")
        assert os.read(descriptor, 100) == b"x = 1\n"
    assert (tmp_path / "moved.py").read_bytes() == b"x = 1\n"


def test_a_process_is_alive_until_it_exits_and_asking_does_not_end_it() -> None:
    """`os.kill(pid, 0)` is the POSIX question; on Windows it would be the answer as well."""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert alive(process.pid)
        # A process just told to end still runs for a moment, so `poll()` would not see it.
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.5)
    finally:
        process.kill()
        process.wait()
    assert not alive(process.pid)


def test_a_program_exits_as_it_was_made_to(tmp_path: Path) -> None:
    passing = program(tmp_path / "passing", passes=True)
    failing = program(tmp_path / "failing", passes=False)
    assert subprocess.run([passing], capture_output=True, check=False).returncode == 0
    assert subprocess.run([failing], capture_output=True, check=False).returncode != 0
