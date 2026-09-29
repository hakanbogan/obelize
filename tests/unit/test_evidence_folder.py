"""`RunFolder`, how `verify` and `undo` reach a run folder: links, stray files, failed writes."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from obelize.evidence.folder import RunFolder
from obelize.native import files
from platforms import junction, link, windows_only


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "repo" / ".obelize" / "runs" / "one" / "verify").mkdir(parents=True)
    (tmp_path / "repo" / ".obelize" / "runs" / "one" / "run.json").write_bytes(b"{}\n")
    return tmp_path / "repo"


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    directory = tmp_path / "outside"
    directory.mkdir()
    (directory / "victim.txt").write_bytes(b"somebody's\n")
    return directory


def folder(root: Path) -> RunFolder:
    return RunFolder(root, ".obelize", "runs", "one")


def test_reads_a_file_under_the_folder(root: Path) -> None:
    assert folder(root).read("run.json") == b"{}\n"


@pytest.mark.parametrize("component", [".obelize", ".obelize/runs", ".obelize/runs/one"])
def test_a_link_at_any_component_of_the_folder_is_refused(
    root: Path, outside: Path, component: str
) -> None:
    """`O_NOFOLLOW` on the last component alone would read straight through these."""
    target = root / component
    target.rename(outside / "moved")
    link(target, outside / "moved")

    with pytest.raises(OSError, match="is a symbolic link or not a directory"):
        folder(root).read("run.json")


def test_a_link_at_the_file_is_refused(root: Path, outside: Path) -> None:
    (root / ".obelize" / "runs" / "one" / "REPORT.md").symlink_to(outside / "victim.txt")

    with pytest.raises(OSError, match=r"REPORT\.md is a symbolic link"):
        folder(root).read("REPORT.md")


def test_a_file_where_a_directory_was_expected_is_refused(root: Path) -> None:
    (root / ".obelize" / "runs" / "one" / "snapshots").write_bytes(b"")

    with pytest.raises(OSError, match="snapshots is a symbolic link or not a directory"):
        folder(root).read("snapshots/before/abc")


def test_a_root_that_is_not_a_directory_is_not_blamed_on_the_folder(tmp_path: Path) -> None:
    """The root is the user's and is followed, so only the names below it are reworded."""
    (tmp_path / "repo").write_bytes(b"")

    with pytest.raises(NotADirectoryError) as raised:
        folder(tmp_path / "repo").read("run.json")

    assert "symbolic link" not in str(raised.value)


def test_no_call_keeps_a_descriptor_open(root: Path) -> None:
    """The lowest free descriptor is the one the next open gets, so a leak moves it."""

    def lowest_free() -> int:
        probe = os.open(os.devnull, os.O_RDONLY)
        os.close(probe)
        return probe

    free = lowest_free()
    folder(root).read("run.json")
    folder(root).write("verify/after/log.txt", b"ran\n")
    folder(root).empty("verify/after")

    assert lowest_free() == free


def test_a_missing_file_is_the_kernels_own_answer(root: Path) -> None:
    """Only a link and a non-directory are reworded; absence reads as absence."""
    with pytest.raises(FileNotFoundError) as absent:
        folder(root).read("REPORT.md")

    assert "symbolic link" not in str(absent.value)


def test_writes_a_file_and_the_directories_below_the_folder(root: Path) -> None:
    folder(root).write("verify/after/log.txt", b"ran\n")

    written = root / ".obelize" / "runs" / "one" / "verify" / "after" / "log.txt"
    assert written.read_bytes() == b"ran\n"
    assert sorted(path.name for path in written.parent.iterdir()) == ["log.txt"]


def test_does_not_create_the_folder_itself(root: Path) -> None:
    """`load` found the folder; recreating one somebody deleted would leave half a run."""
    with pytest.raises(FileNotFoundError):
        RunFolder(root, ".obelize", "runs", "two").write("run.json", b"{}\n")

    assert not (root / ".obelize" / "runs" / "two").exists()


def test_a_link_at_the_name_is_replaced_and_not_followed(root: Path, outside: Path) -> None:
    name = root / ".obelize" / "runs" / "one" / "undo.json"
    name.symlink_to(outside / "victim.txt")

    folder(root).write("undo.json", b"{}\n")

    assert (outside / "victim.txt").read_bytes() == b"somebody's\n"
    assert not name.is_symlink()
    assert name.read_bytes() == b"{}\n"


def test_a_link_planted_at_the_temporary_name_is_not_written_through(
    root: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`O_EXCL` makes the temporary a new file, so a link planted at a guessed name is refused."""
    monkeypatch.setattr("obelize.evidence.folder.secrets.token_hex", lambda _: "guessed")
    (root / ".obelize" / "runs" / "one" / ".guessed.tmp").symlink_to(outside / "victim.txt")

    with pytest.raises(FileExistsError):
        folder(root).write("run.json", b"{}\n")

    assert (outside / "victim.txt").read_bytes() == b"somebody's\n"


def test_a_write_that_fails_leaves_no_temporary_behind(root: Path) -> None:
    """A directory at the name: the rename fails after the temporary exists."""
    (root / ".obelize" / "runs" / "one" / "REPORT.md").mkdir()

    with pytest.raises(IsADirectoryError):
        folder(root).write("REPORT.md", b"# report\n")

    assert sorted(path.name for path in (root / ".obelize" / "runs" / "one").iterdir()) == [
        "REPORT.md",
        "run.json",
        "verify",
    ]


def test_empties_a_directory_and_everything_in_it(root: Path) -> None:
    after = root / ".obelize" / "runs" / "one" / "verify" / "after"
    (after / "deep").mkdir(parents=True)
    (after / "deep" / "log.txt").write_bytes(b"old\n")

    folder(root).empty("verify/after")

    assert not after.exists()
    assert (root / ".obelize" / "runs" / "one" / "verify").is_dir()


def test_emptying_what_is_not_there_is_nothing(root: Path) -> None:
    folder(root).empty("verify/after")

    assert list((root / ".obelize" / "runs" / "one" / "verify").iterdir()) == []


def test_emptying_below_a_directory_that_is_not_there_makes_it(root: Path) -> None:
    verify = root / ".obelize" / "runs" / "one" / "verify"
    verify.rmdir()

    folder(root).empty("verify/after")

    assert list(verify.iterdir()) == []


@pytest.mark.parametrize("shape", ["link", "file"])
def test_a_link_or_a_file_at_the_name_is_not_emptied(root: Path, outside: Path, shape: str) -> None:
    after = root / ".obelize" / "runs" / "one" / "verify" / "after"
    if shape == "link":
        link(after, outside)
    else:
        after.write_bytes(b"")

    with pytest.raises(OSError, match="after is a symbolic link or not a directory"):
        folder(root).empty("verify/after")

    assert (outside / "victim.txt").read_bytes() == b"somebody's\n"
    assert after.is_symlink() or after.is_file()


def test_a_junction_at_the_name_is_not_emptied(
    root: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' `lstat`, stubbed: a junction is a directory whose reparse tag names another path."""
    status = files.status

    def reparse(parent: files.Handle, name: str) -> Any:
        found = status(parent, name)
        return (
            SimpleNamespace(st_mode=found.st_mode, st_reparse_tag=0xA0000003)
            if name == "after"
            else found
        )

    after = root / ".obelize" / "runs" / "one" / "verify" / "after"
    after.mkdir()
    (after / "kept.txt").write_bytes(b"kept\n")
    monkeypatch.setattr(files, "status", reparse)
    with pytest.raises(OSError, match="after is a symbolic link or not a directory"):
        folder(root).empty("verify/after")
    assert (after / "kept.txt").read_bytes() == b"kept\n"


@windows_only("POSIX has no junction; the stubbed reparse tag above stands in for one")
def test_a_real_junction_at_the_name_is_not_emptied(root: Path, outside: Path) -> None:
    """Control: `S_ISDIR`, all `empty` asked before, is true for it."""
    after = root / ".obelize" / "runs" / "one" / "verify" / "after"
    junction(after, outside)
    assert stat.S_ISDIR(after.lstat().st_mode)
    with pytest.raises(OSError, match="after is a symbolic link or not a directory"):
        folder(root).empty("verify/after")
    assert (outside / "victim.txt").read_bytes() == b"somebody's\n"
