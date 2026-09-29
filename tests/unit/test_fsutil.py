"""The path guard and the writer, including the races no repository fixture can pose.

Guard trees sit under a resolved root, `/tmp` and a symlinked root; the last keeps the macOS
`/tmp` trap live on Linux, where `/tmp` is a real directory.
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from obelize import fsutil
from obelize.fsutil import contained, refusal
from obelize.models import PATH_REFUSALS, SKIP_REASONS
from obelize.native import files
from platforms import AS_ROOT, MODE_BITS, deny, junction, link, posix_only, windows_only


def _build(root: Path) -> None:
    """A small tree, plus the directory outside it that the links point at."""
    outside = root.parent / "outside"
    (outside / "pkg").mkdir(parents=True, exist_ok=True)
    (outside / "secret.py").write_text("secret = True\n", encoding="utf-8", newline="\n")
    (outside / "pkg" / "inner.py").write_text("inner = True\n", encoding="utf-8", newline="\n")
    root.mkdir(parents=True, exist_ok=True)
    (root / "inside.py").write_text("inside = True\n", encoding="utf-8", newline="\n")
    (root / "link_inside.py").symlink_to("inside.py")
    (root / "dangling.py").symlink_to("nowhere.py")
    (root / "loop.py").symlink_to("loop.py")
    link(root / "linked_pkg", outside / "pkg")
    sealed = root / "sealed"
    sealed.mkdir()
    (sealed / "hidden.py").write_text("hidden = True\n", encoding="utf-8", newline="\n")


TMP = posix_only("only POSIX has /tmp; the symlinked root poses its macOS trap everywhere")


@pytest.fixture(scope="session", params=["resolved", pytest.param("tmp", marks=TMP), "symlinked"])
def root(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Path]:
    if request.param == "tmp":
        base = Path(tempfile.mkdtemp(dir="/tmp", prefix="obelize-fsutil-"))
    else:
        base = tmp_path_factory.mktemp("fsutil")
    if request.param == "symlinked":
        (base / "real").mkdir()
        link(base / "reached-through-a-link", base / "real")
        built = base / "reached-through-a-link" / "repo"
    else:
        built = base / "repo"
    _build(built)
    with deny(built / "sealed"):
        yield built
    shutil.rmtree(base, ignore_errors=True)


def _naive(root: Path, candidate: Path) -> bool:
    """The guard with the root left unresolved: the version that finds nothing."""
    try:
        return candidate.resolve(strict=True).is_relative_to(root)
    except (OSError, RuntimeError):
        return False


def test_a_file_inside_the_root_is_contained(root: Path) -> None:
    assert contained(root, root / "inside.py") is True


def test_the_unresolved_root_is_the_mistake_this_guard_exists_for(root: Path) -> None:
    assert _naive(root, root / "inside.py") is (root == root.resolve())


def test_a_root_reached_through_a_link_defeats_the_unresolved_check(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.py").write_text("a = 1\n", encoding="utf-8", newline="\n")
    through_a_link = tmp_path / "checkout"
    link(through_a_link, real)
    assert _naive(through_a_link, through_a_link / "a.py") is False
    assert contained(through_a_link, through_a_link / "a.py") is True


def test_a_path_outside_the_root_is_not_contained(root: Path) -> None:
    assert contained(root, root.parent / "outside" / "secret.py") is False


def test_a_dangling_symlink_is_not_contained(root: Path) -> None:
    assert contained(root, root / "dangling.py") is False


def test_a_symlink_loop_is_not_contained(root: Path) -> None:
    assert contained(root, root / "loop.py") is False


def test_an_ordinary_file_is_not_refused(root: Path) -> None:
    assert refusal(root, root / "inside.py") is None


def test_a_symlink_that_points_into_the_root_is_still_refused(root: Path) -> None:
    """Contained, but following it would scan one file twice and rewrite it via a foreign name."""
    assert contained(root, root / "link_inside.py") is True
    assert refusal(root, root / "link_inside.py") == "symlink"


def test_a_path_under_a_linked_directory_resolves_outside_the_root(root: Path) -> None:
    """No listing produces it: only the parent is a link, so `is_symlink` alone misses it."""
    escape = root / "linked_pkg" / "inner.py"
    assert escape.is_symlink() is False
    assert refusal(root, escape) == "outside_root"


def test_a_listed_path_that_is_gone_is_missing_rather_than_an_escape(root: Path) -> None:
    """`rm` on a tracked file leaves its name in the index, and so in the listing."""
    assert refusal(root, root / "removed.py") == "missing"


def test_a_directory_is_not_a_file(root: Path) -> None:
    """What drops a gitlink, which git lists as one ordinary path entry."""
    assert refusal(root, root / "sealed") == "not_a_file"


@pytest.mark.skipif(AS_ROOT, reason="root ignores the permission bits this test removes")
def test_a_path_the_filesystem_will_not_answer_about_is_refused(root: Path) -> None:
    """`Path.is_symlink` swallows the denial from 3.14, so the guard reads `lstat`'s errno."""
    assert refusal(root, root / "sealed" / "hidden.py") == "unreadable"


@pytest.mark.parametrize(
    ("mode", "tag", "reason"),
    [(stat.S_IFDIR | 0o755, 0xA0000003, "symlink"), (stat.S_IFREG | 0o644, 0x9000601A, None)],
    ids=["junction", "cloud-placeholder"],
)
def test_a_reparse_point_that_names_another_path_is_a_link_and_no_other_is(
    root: Path, monkeypatch: pytest.MonkeyPatch, mode: int, tag: int, reason: str | None
) -> None:
    """Windows' `lstat`, stubbed: a junction is a directory whose tag names another path; a
    OneDrive placeholder's tag does not, and it is read as the file it is."""
    real = Path.lstat

    def lstat(path: Path) -> Any:
        found = real(path)
        return (
            SimpleNamespace(st_mode=mode, st_reparse_tag=tag) if path.name == "inside.py" else found
        )

    monkeypatch.setattr(Path, "lstat", lstat)
    assert refusal(root, root / "inside.py") == reason


@windows_only("POSIX has no junction; the stubbed reparse tag above stands in for one")
def test_a_junction_is_refused_as_a_link(tree: Path) -> None:
    """Control: `is_symlink` and `S_ISLNK` both miss it, which is all the guard asked before."""
    junction(tree / "joined", tree / "pkg")
    assert not (tree / "joined").is_symlink()
    assert not stat.S_ISLNK((tree / "joined").lstat().st_mode)
    assert refusal(tree, tree / "joined") == "symlink"


def test_a_listed_path_under_something_that_is_not_a_directory_is_missing(root: Path) -> None:
    """`ENOTDIR`: the index still names `pkg/app.py` after `pkg` became a file."""
    (root / "pkg").write_text("", encoding="utf-8", newline="\n")
    assert refusal(root, root / "pkg" / "app.py") == "missing"


def test_a_listed_path_under_a_symbolic_link_loop_is_missing(root: Path) -> None:
    """`ELOOP`: nothing can be at a path whose parent never resolves."""
    (root / "loop").symlink_to("loop")
    assert refusal(root, root / "loop" / "app.py") == "missing"


def test_every_refusal_this_module_can_return_is_a_published_skip_reason(root: Path) -> None:
    seen = {
        refusal(root, root / name)
        for name in ("inside.py", "link_inside.py", "removed.py", "sealed", "linked_pkg")
    }
    assert seen - {None} <= PATH_REFUSALS <= SKIP_REASONS
    assert PATH_REFUSALS <= fsutil.WRITE_REFUSALS


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    (tmp_path / "pkg" / "mod.py").write_text("INNER = 1\n", encoding="utf-8", newline="\n")
    return tmp_path


def temporaries(root: Path) -> list[str]:
    return [str(path.relative_to(root)) for path in root.rglob(f"*{fsutil.TEMPORARY_SUFFIX}")]


def test_the_digest_is_the_one_every_other_module_records() -> None:
    assert fsutil.sha256(b"") == hashlib.sha256(b"").hexdigest()


def test_reading_a_name_that_is_a_symlink_refuses_rather_than_follows(tree: Path) -> None:
    """`O_NOFOLLOW` keeps the walker's earlier `refusal` answer true if the name changes."""
    secret = tree.parent / "secret.py"
    secret.write_text("SECRET = True\n", encoding="utf-8", newline="\n")
    (tree / "link.py").symlink_to(secret)
    assert fsutil.read(tree / "app.py") == b"VALUE = 1\n"
    with pytest.raises(OSError, match="symbolic link") as raised:
        fsutil.read(tree / "link.py")
    assert raised.value.errno == errno.ELOOP


def test_a_write_replaces_the_bytes_and_leaves_no_temporary(tree: Path) -> None:
    assert fsutil.write(tree, "app.py", b"VALUE = 2\n") is None
    assert (tree / "app.py").read_bytes() == b"VALUE = 2\n"
    assert temporaries(tree) == []


def test_a_write_reaches_a_file_in_a_subdirectory(tree: Path) -> None:
    assert fsutil.write(tree, "pkg/mod.py", b"INNER = 2\n") is None
    assert (tree / "pkg" / "mod.py").read_bytes() == b"INNER = 2\n"


def test_a_repository_that_is_itself_reached_through_a_link_is_written(tmp_path: Path) -> None:
    """Only the root skips `O_NOFOLLOW`: the user chose it; components below it can be swapped."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "app.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    root = tmp_path / "checkout"
    link(root, real)
    assert fsutil.write(root, "app.py", b"VALUE = 2\n") is None
    assert (real / "app.py").read_bytes() == b"VALUE = 2\n"


@MODE_BITS
def test_a_write_keeps_the_mode_the_file_already_had(tree: Path) -> None:
    """`mkstemp` makes a 0600 file, so temp-plus-rename drops an executable bit unless restored."""
    (tree / "app.py").chmod(0o755)
    assert fsutil.write(tree, "app.py", b"VALUE = 2\n") is None
    assert (tree / "app.py").stat().st_mode & 0o777 == 0o755


@MODE_BITS
def test_the_temporary_is_private_until_it_takes_the_file_s_mode(
    monkeypatch: pytest.MonkeyPatch, tree: Path
) -> None:
    """The new bytes of a 0600 file must not sit in a file others can read, even briefly."""
    (tree / "app.py").chmod(0o600)
    before: list[int] = []
    set_mode = files.set_mode

    def spy(descriptor: int, mode: int) -> None:
        before.append(os.fstat(descriptor).st_mode & 0o777)
        set_mode(descriptor, mode)

    monkeypatch.setattr(files, "set_mode", spy)
    assert fsutil.write(tree, "app.py", b"VALUE = 2\n") is None
    assert [mode & 0o077 for mode in before] == [0]


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../outside.py", "pkg/../../outside.py", ""],
    ids=["absolute", "climbs", "climbs-and-returns", "empty"],
)
def test_a_path_that_is_not_a_relative_path_that_stays_put_is_refused(
    tree: Path, path: str
) -> None:
    """`Path("/repo") / "/etc/passwd"` is `/etc/passwd`; any `..` is refused, even if it returns."""
    assert fsutil.write(tree, path, b"x = 1\n") == "outside_root"


def test_an_absolute_path_is_refused_even_when_it_names_a_file_inside_the_root(
    tree: Path,
) -> None:
    """Contained, but write paths are repository-relative; `openat` ignores its fd for this one."""
    assert refusal(tree, tree / "app.py") is None
    assert fsutil.write(tree, str(tree / "app.py"), b"VALUE = 2\n") == "outside_root"
    assert (tree / "app.py").read_bytes() == b"VALUE = 1\n"


def test_a_name_the_system_reserves_is_refused_before_it_is_read(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' answer, stubbed: there `app.py:x` names a stream and `aux.py` a device. The stub
    answers for the whole path only, since a directory's name can be one too."""
    opened: list[Path] = []
    read = fsutil.read

    def spy(path: Path) -> bytes:
        opened.append(path)
        return read(path)

    monkeypatch.setattr(files, "reserved", lambda path: path == "pkg/mod.py")
    monkeypatch.setattr(fsutil, "read", spy)
    assert fsutil.write(tree, "pkg/mod.py", b"INNER = 2\n") == "outside_root"
    change = fsutil.Change(path="pkg/mod.py", before=b"INNER = 1\n", after=b"INNER = 2\n")
    applied = fsutil.apply(tree, [change], allow_dirty=True)
    assert applied.refused == (fsutil.Refused(path="pkg/mod.py", reason="outside_root"),)
    assert opened == []
    assert (tree / "pkg" / "mod.py").read_bytes() == b"INNER = 1\n"


@posix_only("Windows reserves these names; the test above gives its answer here")
@pytest.mark.parametrize("name", ["aux.py", "COM1", "app.py:x", "pkg.", "tail "])
def test_posix_writes_the_names_windows_reserves(tree: Path, name: str) -> None:
    (tree / name).write_bytes(b"VALUE = 1\n")
    assert fsutil.write(tree, name, b"VALUE = 2\n") is None
    assert (tree / name).read_bytes() == b"VALUE = 2\n"


@windows_only("POSIX holds these names as written; the stubbed test above refuses them there")
@pytest.mark.parametrize(
    "name",
    ["app.py:x", "app.py.", "app.py ", "pkg\\mod.py", "NUL", "{drive}app.py"],
    ids=["stream", "trailing-dot", "trailing-space", "backslash", "device", "drive"],
)
def test_a_name_windows_opens_as_something_else_is_refused(tree: Path, name: str) -> None:
    """Control: written by path, the name lands somewhere, and no entry of that name appears."""
    name = name.format(drive=tree.drive)
    before = {path: path.read_bytes() for path in tree.rglob("*") if path.is_file()}
    assert fsutil.write(tree, name, b"VALUE = 2\n") == "outside_root"
    assert {path: path.read_bytes() for path in tree.rglob("*") if path.is_file()} == before
    (tree / name).write_bytes(b"CONTROL = 1\n")
    assert name not in os.listdir(tree)


def test_a_name_that_became_a_symlink_is_refused_rather_than_replaced(tree: Path) -> None:
    """The guard is asked again inside `write`, because a plan can be raced."""
    (tree / "link.py").symlink_to(tree / "app.py")
    assert fsutil.write(tree, "link.py", b"VALUE = 2\n") == "symlink"
    assert (tree / "app.py").read_bytes() == b"VALUE = 1\n"


def test_a_file_that_is_gone_is_not_created(tree: Path) -> None:
    assert fsutil.write(tree, "absent.py", b"x = 1\n") == "missing"
    assert (tree / "absent.py").exists() is False


def test_a_directory_that_became_a_link_is_not_written_through(
    monkeypatch: pytest.MonkeyPatch, tree: Path
) -> None:
    """`rename` resolves directories above its target; the guard is stubbed to test the descent."""
    outside = tree.parent / "elsewhere"
    outside.mkdir()
    (outside / "mod.py").write_text("THEIRS = 1\n", encoding="utf-8", newline="\n")
    (tree / "pkg").rename(tree / "real")
    link(tree / "pkg", outside)
    monkeypatch.setattr(fsutil, "refusal", lambda *_arguments: None)
    assert fsutil.write(tree, "pkg/mod.py", b"OURS = 1\n") == "unreadable"
    assert (outside / "mod.py").read_bytes() == b"THEIRS = 1\n"


def test_a_rename_that_fails_leaves_the_file_and_no_temporary(
    monkeypatch: pytest.MonkeyPatch, tree: Path
) -> None:
    """The rename is the only destructive step; when it fails the temporary is removed too."""

    def refuse(*_arguments: object) -> None:
        raise OSError("no rename today")

    monkeypatch.setattr(files, "rename", refuse)
    assert fsutil.write(tree, "app.py", b"VALUE = 2\n") == "unreadable"
    assert (tree / "app.py").read_bytes() == b"VALUE = 1\n"
    assert temporaries(tree) == []


def test_a_plan_is_written_in_path_order_with_both_hashes(tree: Path) -> None:
    applied = fsutil.apply(
        tree,
        [
            fsutil.Change(path="pkg/mod.py", before=b"INNER = 1\n", after=b"INNER = 2\n"),
            fsutil.Change(path="app.py", before=b"VALUE = 1\n", after=b"VALUE = 2\n"),
        ],
    )
    assert [row.path for row in applied.written] == ["app.py", "pkg/mod.py"]
    assert applied.blocked is False
    assert applied.written[0].before_sha256 == fsutil.sha256(b"VALUE = 1\n")
    assert applied.written[0].after_sha256 == fsutil.sha256(b"VALUE = 2\n")


def test_a_file_that_changed_since_the_plan_read_it_stops_the_whole_apply(tree: Path) -> None:
    """An edit made after the dirty-tree check (TM-8); a refusal must change nothing at all."""
    (tree / "app.py").write_text("VALUE = 99\n", encoding="utf-8", newline="\n")
    applied = fsutil.apply(
        tree,
        [
            fsutil.Change(path="app.py", before=b"VALUE = 1\n", after=b"VALUE = 2\n"),
            fsutil.Change(path="pkg/mod.py", before=b"INNER = 1\n", after=b"INNER = 2\n"),
        ],
    )
    assert applied.written == ()
    assert applied.blocked is True
    assert [(row.path, row.reason) for row in applied.refused] == [
        ("app.py", "file_changed_since_read")
    ]
    assert (tree / "pkg" / "mod.py").read_bytes() == b"INNER = 1\n"


@pytest.mark.parametrize(
    ("name", "reason"),
    [("link.py", "symlink"), ("absent.py", "missing"), ("/etc/passwd", "outside_root")],
    ids=["symlink", "missing", "absolute"],
)
def test_the_guard_stops_an_apply_before_anything_is_written(
    tree: Path, name: str, reason: str
) -> None:
    (tree / "link.py").symlink_to(tree / "app.py")
    applied = fsutil.apply(
        tree,
        [
            fsutil.Change(path=name, before=b"", after=b"x = 1\n"),
            fsutil.Change(path="app.py", before=b"VALUE = 1\n", after=b"VALUE = 2\n"),
        ],
    )
    assert [(row.path, row.reason) for row in applied.refused] == [(name, reason)]
    assert applied.written == ()
    assert (tree / "app.py").read_bytes() == b"VALUE = 1\n"


@pytest.mark.skipif(AS_ROOT, reason="root ignores the permission bits this test removes")
def test_a_file_the_preflight_cannot_read_is_refused(tree: Path) -> None:
    with deny(tree / "app.py"):
        applied = fsutil.apply(
            tree, [fsutil.Change(path="app.py", before=b"VALUE = 1\n", after=b"VALUE = 2\n")]
        )
    assert [(row.path, row.reason) for row in applied.refused] == [("app.py", "unreadable")]


def test_a_write_that_fails_after_the_preflight_passed_is_reported_not_rolled_back(
    monkeypatch: pytest.MonkeyPatch, tree: Path
) -> None:
    """A post-preflight failure is a race: written files are whole, and a rollback can fail too."""
    original = files.rename

    def refuse(parent: files.Handle, source: str, target: str) -> None:
        if target == "mod.py":
            raise OSError("raced")
        original(parent, source, target)

    monkeypatch.setattr(files, "rename", refuse)
    applied = fsutil.apply(
        tree,
        [
            fsutil.Change(path="app.py", before=b"VALUE = 1\n", after=b"VALUE = 2\n"),
            fsutil.Change(path="pkg/mod.py", before=b"INNER = 1\n", after=b"INNER = 2\n"),
        ],
    )
    assert [row.path for row in applied.written] == ["app.py"]
    assert [(row.path, row.reason) for row in applied.refused] == [("pkg/mod.py", "unreadable")]
    assert (tree / "app.py").read_bytes() == b"VALUE = 2\n"
    assert (tree / "pkg" / "mod.py").read_bytes() == b"INNER = 1\n"
