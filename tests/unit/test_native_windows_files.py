"""`native.files` on Windows: NT calls relative to an open directory, never through a link.

Each refusal is first shown to escape by the plain call it stands in for, and each other test
first shows that what it depends on is really there, so a green run cannot pass over nothing.
"""

from __future__ import annotations

import errno
import itertools
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from obelize import fsutil
from obelize.evidence.folder import RunFolder
from obelize.native import _win32, files
from platforms import held, junction, link, windows_only

pytestmark = windows_only("NT calls; `test_native_win32.py` checks what they pass on any system")

# A OneDrive placeholder's tag: a reparse point that names no other path.
CLOUD = 0x9000601A


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "app.py").write_bytes(b"VALUE = 1\n")
    (root / "pkg" / "mod.py").write_bytes(b"INNER = 1\n")
    return root


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    directory = tmp_path / "outside"
    directory.mkdir()
    (directory / "mod.py").write_bytes(b"THEIRS = 1\n")
    return directory


def snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_a_directory_swapped_for_a_junction_is_not_written_through(
    tree: Path, outside: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard is stubbed, as a swap between plan and write gets past it. Control: a rename by
    path lands in the junction's target."""
    (tree / "pkg").rename(tree / "real")
    junction(tree / "pkg", outside)
    (tree / "control.tmp").write_bytes(b"CONTROL = 1\n")
    os.replace(tree / "control.tmp", tree / "pkg" / "control.py")
    assert (outside / "control.py").read_bytes() == b"CONTROL = 1\n"

    monkeypatch.setattr(fsutil, "refusal", lambda *_arguments: None)
    assert fsutil.write(tree, "pkg/mod.py", b"OURS = 1\n") == "unreadable"
    assert (outside / "mod.py").read_bytes() == b"THEIRS = 1\n"


@pytest.mark.parametrize("component", [".obelize", ".obelize/runs", ".obelize/runs/one"])
def test_a_junction_at_any_component_of_a_run_folder_is_refused(
    tmp_path: Path, component: str
) -> None:
    """Control: a plain open reads the run through the junction."""
    root = tmp_path / "repo"
    (root / ".obelize" / "runs" / "one" / "verify" / "after").mkdir(parents=True)
    (root / ".obelize" / "runs" / "one" / "run.json").write_bytes(b"{}\n")
    moved = tmp_path / "moved"
    (root / component).rename(moved)
    junction(root / component, moved)
    assert (root / ".obelize" / "runs" / "one" / "run.json").read_bytes() == b"{}\n"
    before = snapshot(moved)

    folder = RunFolder(root, ".obelize", "runs", "one")
    with pytest.raises(OSError, match="is a symbolic link or not a directory"):
        folder.read("run.json")
    with pytest.raises(OSError, match="is a symbolic link or not a directory"):
        folder.write("undo.json", b"{}\n")
    with pytest.raises(OSError, match="is a symbolic link or not a directory"):
        folder.empty("verify/after")
    assert snapshot(moved) == before


PAYLOAD = b"crlf\r\nlf\nbare\rend\x1aafter\x00"


def test_bytes_come_back_as_written_through_the_writer_and_the_run_folder(tree: Path) -> None:
    """Control: a descriptor opened without `O_BINARY` translates them."""
    (tree / "control.bin").write_bytes(PAYLOAD)
    descriptor = os.open(tree / "control.bin", os.O_RDONLY)
    try:
        assert os.read(descriptor, 100) != PAYLOAD
    finally:
        os.close(descriptor)

    assert fsutil.write(tree, "app.py", PAYLOAD) is None
    assert fsutil.read(tree / "app.py") == PAYLOAD
    assert (tree / "app.py").read_bytes() == PAYLOAD
    folder = RunFolder(tree, "pkg")
    folder.write("payload.bin", PAYLOAD)
    assert folder.read("payload.bin") == PAYLOAD
    assert (tree / "pkg" / "payload.bin").read_bytes() == PAYLOAD
    assert (tree / "pkg" / "payload.bin").stat().st_mode & stat.S_IWRITE


def test_a_file_another_program_holds_open_is_replaced(tree: Path) -> None:
    """Control: the holder still reads the bytes it opened, so the file was open when the rename
    replaced it."""
    with held(tree / "app.py") as descriptor:
        assert fsutil.write(tree, "app.py", b"VALUE = 2\n") is None
        assert os.read(descriptor, 100) == b"VALUE = 1\n"
    assert (tree / "app.py").read_bytes() == b"VALUE = 2\n"


def test_a_volume_without_posix_semantics_renames_and_deletes_with_the_classic_classes(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAT, or a server that has no POSIX semantics. Control: `os.remove` cannot delete the
    read-only file `empty` deletes, and the spy sees only the classic classes."""
    after = tree / "verify" / "after"
    (after / "deep").mkdir(parents=True)
    (after / "deep" / "locked.txt").write_bytes(b"x\n")
    (after / "deep" / "locked.txt").chmod(0o444)
    (tree / "sibling.txt").write_bytes(b"x\n")
    (tree / "sibling.txt").chmod(0o444)
    with pytest.raises(PermissionError):
        os.remove(tree / "sibling.txt")

    classes: list[int] = []
    set_information = _win32.set_information

    def spy(handle: int, information_class: int, information: Any, name: str | None) -> None:
        classes.append(information_class)
        set_information(handle, information_class, information, name)

    monkeypatch.setattr(_win32, "posix_semantics", lambda _handle, _name: False)
    monkeypatch.setattr(_win32, "set_information", spy)
    assert fsutil.write(tree, "app.py", b"VALUE = 2\n") is None
    assert (tree / "app.py").read_bytes() == b"VALUE = 2\n"
    RunFolder(tree, "verify").empty("after")
    assert not after.exists()
    # 4 sets the attributes, 10 renames and 13 deletes; 64 and 65 are their POSIX forms.
    assert set(classes) == {4, 10, 13}


def test_a_read_only_file_is_rewritten_and_stays_read_only(tree: Path) -> None:
    """Windows keeps the read-only attribute where POSIX keeps a mode. Control: a plain open
    cannot write the file."""
    (tree / "app.py").chmod(0o444)
    with pytest.raises(PermissionError):
        (tree / "app.py").write_bytes(b"CONTROL = 1\n")

    assert fsutil.write(tree, "app.py", b"VALUE = 2\n") is None
    assert (tree / "app.py").read_bytes() == b"VALUE = 2\n"
    assert not (tree / "app.py").stat().st_mode & stat.S_IWRITE
    assert fsutil.write(tree, "pkg/mod.py", b"INNER = 2\n") is None
    assert (tree / "pkg" / "mod.py").stat().st_mode & stat.S_IWRITE


def test_emptying_deletes_the_links_below_as_links(tree: Path, outside: Path) -> None:
    """Control: `os.walk` goes through the junction into the outside directory."""
    after = tree / "verify" / "after"
    (after / "deep").mkdir(parents=True)
    (after / "deep" / "log.txt").write_bytes(b"ran\n")
    junction(after / "deep" / "joined", outside)
    link(after / "linked", outside)
    link(after / "pointed.py", outside / "mod.py")
    assert "mod.py" in [name for _, _, names in os.walk(after) for name in names]

    RunFolder(tree, "verify").empty("after")
    assert not after.exists()
    assert snapshot(outside) == {"mod.py": b"THEIRS = 1\n"}


def test_a_link_at_the_name_to_remove_is_refused_as_rmtree_refuses_one(
    tree: Path, outside: Path
) -> None:
    """The run folder asks first, and the seam refuses too. Control: a walk of the name by path
    lists the outside directory."""
    junction(tree / "joined", outside)
    assert "mod.py" in [name for _, _, names in os.walk(tree / "joined") for name in names]

    parent = files.root(tree)
    try:
        with pytest.raises(OSError, match="Is a symbolic link or a junction"):
            files.remove_tree(parent, "joined")
    finally:
        files.close(parent)
    assert (tree / "joined").is_junction()
    assert snapshot(outside) == {"mod.py": b"THEIRS = 1\n"}


def test_a_reparse_point_that_names_no_other_path_is_read_through_its_filter(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A OneDrive placeholder, stubbed on every name: it is opened again without the flag and
    must be the same file. Control: the identities were compared."""
    attribute_tag = _win32.attribute_tag
    identity = _win32.identity
    compared: list[str] = []

    def placeholder(handle: int, name: str) -> tuple[int, int]:
        attributes, _ = attribute_tag(handle, name)
        return attributes | _win32.FILE_ATTRIBUTE_REPARSE_POINT, CLOUD

    def spy(handle: int, name: str) -> bytes:
        compared.append(name)
        return identity(handle, name)

    monkeypatch.setattr(_win32, "attribute_tag", placeholder)
    monkeypatch.setattr(_win32, "identity", spy)
    assert fsutil.read(tree / "app.py") == b"VALUE = 1\n"
    assert RunFolder(tree, "pkg").read("mod.py") == b"INNER = 1\n"
    assert fsutil.write(tree, "pkg/mod.py", b"INNER = 2\n") is None
    assert (tree / "pkg" / "mod.py").read_bytes() == b"INNER = 2\n"
    assert {str(tree / "app.py"), "pkg", "mod.py"} <= set(compared)


def test_a_reparse_point_whose_filter_gives_another_file_is_refused(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: with the identities left alone, the same reads succeed."""
    attribute_tag = _win32.attribute_tag

    def placeholder(handle: int, name: str) -> tuple[int, int]:
        attributes, _ = attribute_tag(handle, name)
        return attributes | _win32.FILE_ATTRIBUTE_REPARSE_POINT, CLOUD

    monkeypatch.setattr(_win32, "attribute_tag", placeholder)
    assert fsutil.read(tree / "app.py") == b"VALUE = 1\n"
    assert RunFolder(tree, "pkg").read("mod.py") == b"INNER = 1\n"

    counter = itertools.count()
    monkeypatch.setattr(_win32, "identity", lambda _handle, _name: bytes([next(counter)]))
    with pytest.raises(OSError, match="Became another file while it was opened") as raised:
        fsutil.read(tree / "app.py")
    assert raised.value.errno == errno.ELOOP
    with pytest.raises(OSError, match="pkg is a symbolic link or not a directory"):
        RunFolder(tree, "pkg").read("mod.py")


def test_a_repository_reached_through_a_junction_is_written(tmp_path: Path) -> None:
    """The root is the user's and is followed, the Windows form of macOS's `/tmp`. Control:
    below a root, the same junction is refused."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "app.py").write_bytes(b"VALUE = 1\n")
    junction(tmp_path / "checkout", real)
    parent = files.root(tmp_path)
    try:
        with pytest.raises(OSError, match="Is a symbolic link or a junction") as raised:
            files.directory(parent, "checkout")
    finally:
        files.close(parent)
    assert raised.value.errno == errno.ELOOP

    assert fsutil.write(tmp_path / "checkout", "app.py", b"VALUE = 2\n") is None
    assert (real / "app.py").read_bytes() == b"VALUE = 2\n"


def test_an_empty_name_is_refused_rather_than_taken_for_the_directory(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: without the check, an empty name opens the directory it is relative to."""
    parent = files.root(tree)
    try:
        encode = _win32.encode
        monkeypatch.setattr(_win32, "encode", lambda name: name.encode("utf-16-le"))
        assert stat.S_ISDIR(files.status(parent, "").st_mode)
        monkeypatch.setattr(_win32, "encode", encode)

        calls: list[Callable[[files.Handle, str], object]] = [
            files.status,
            files.unlink,
            files.remove_tree,
            files.directory,
            files.open_at,
        ]
        for call in calls:
            with pytest.raises(OSError, match="Not a name within one directory"):
                call(parent, "")
    finally:
        files.close(parent)
    assert snapshot(tree) == {"app.py": b"VALUE = 1\n", "pkg/mod.py": b"INNER = 1\n"}
