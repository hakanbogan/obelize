"""`obelize undo`: the skip reasons that need a staged filesystem, and the absent `--force`.

The full revert and the edited-file skip are graded by the oracle.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from obelize import fsutil
from obelize.cli import app
from obelize.models import UNDO_SKIPS
from obelize.native import files
from platforms import AS_ROOT, PYTHON, deny, link

runner = CliRunner()

PACK = "gemini/google-generativeai-to-google-genai"
QUIET = f"{PYTHON} -c pass"

LEGACY = """import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(LEGACY, encoding="utf-8")
    (root / "requirements.txt").write_text("google-generativeai==0.8.6\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "work"], check=True)
    for key, value in (("user.name", "t"), ("user.email", "t@t.invalid")):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", "commit", "-qm", "before"],
        check=True,
    )
    return root


@pytest.fixture
def run_id(tree: Path) -> str:
    return applied(tree)


@pytest.fixture
def nested_run(tree: Path) -> str:
    """A run whose legacy file is one directory down, so its recorded path holds a directory."""
    (tree / "pkg").mkdir()
    subprocess.run(["git", "-C", str(tree), "mv", "app.py", "pkg/app.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tree), "-c", "commit.gpgsign=false", "commit", "-qm", "nested"],
        check=True,
    )
    return applied(tree)


def applied(tree: Path) -> str:
    result = runner.invoke(
        app, ["fix", "--repo", str(tree), "--pack", PACK, "--apply", "--verify", QUIET]
    )
    assert result.exit_code == 0, result.output
    return (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()


def undo(tree: Path, run_id: str) -> Result:
    return runner.invoke(app, ["undo", "--repo", str(tree), "--run", run_id])


def document(tree: Path, run_id: str) -> dict[str, Any]:
    path = tree / ".obelize" / "runs" / run_id / "undo.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def row(tree: Path, run_id: str, path: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [
        one for one in document(tree, run_id)["files"] if one["path"] == path
    ]
    assert len(rows) == 1
    return rows[0]


def test_there_is_no_force_flag(tree: Path, run_id: str) -> None:
    """Typed rather than read from `--help`, whose text itself says "there is no --force"."""
    result = runner.invoke(app, ["undo", "--repo", str(tree), "--run", run_id, "--force"])
    assert result.exit_code == 2
    assert "no such option" in result.output.lower()
    assert "there is no --force" in runner.invoke(app, ["undo", "--help"]).output


def test_a_run_id_that_is_not_one_is_refused_before_it_becomes_a_path(tree: Path) -> None:
    assert undo(tree, "../../etc").exit_code == 2


def test_a_dry_run_wrote_nothing_to_put_back(tree: Path) -> None:
    runner.invoke(app, ["fix", "--repo", str(tree), "--pack", PACK])
    plan = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    result = undo(tree, plan)
    assert result.exit_code == 2
    assert "is a 'plan' run" in result.output


def test_a_repo_that_is_not_a_directory_is_a_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["undo", "--repo", str(tmp_path / "gone"), "--run", "20260101T000000Z-deadbeef"]
    )
    assert result.exit_code == 2


def test_a_file_that_is_gone_is_skipped_with_the_guard_s_own_word(tree: Path, run_id: str) -> None:
    (tree / "app.py").unlink()
    result = undo(tree, run_id)
    assert result.exit_code == 4
    skipped = row(tree, run_id, "app.py")
    assert skipped["reason"] == "missing"
    assert skipped["current_sha256"] is None
    assert row(tree, run_id, "requirements.txt")["outcome"] == "reverted"


def test_a_file_replaced_by_a_directory_is_not_a_file(tree: Path, run_id: str) -> None:
    (tree / "app.py").unlink()
    (tree / "app.py").mkdir()
    assert undo(tree, run_id).exit_code == 4
    assert row(tree, run_id, "app.py")["reason"] == "not_a_file"


def test_a_file_replaced_by_a_link_is_never_followed(tree: Path, run_id: str) -> None:
    """The read is `O_NOFOLLOW`, so the guard's answer holds from the check to the write."""
    (tree / "app.py").unlink()
    (tree / "app.py").symlink_to(tree / "requirements.txt")
    assert undo(tree, run_id).exit_code == 4
    assert row(tree, run_id, "app.py")["reason"] == "symlink"


def test_a_snapshot_that_is_not_what_its_name_says_is_not_written(tree: Path, run_id: str) -> None:
    """Each copy is checked against its content-addressed name before it is written back."""
    folder = tree / ".obelize" / "runs" / run_id
    before = sorted((folder / "snapshots" / "before").iterdir())
    target = next(path for path in before if path.read_text(encoding="utf-8") == LEGACY)
    target.write_bytes(b"not what this file is called\n")
    assert undo(tree, run_id).exit_code == 4
    assert row(tree, run_id, "app.py")["reason"] == "snapshot_unusable"
    # A missing copy. `requirements.txt` was restored above, so its row is now `hash_mismatch`.
    target.unlink()
    assert undo(tree, run_id).exit_code == 4
    assert row(tree, run_id, "app.py")["reason"] == "snapshot_unusable"
    assert row(tree, run_id, "requirements.txt")["reason"] == "hash_mismatch"


@pytest.mark.skipif(AS_ROOT, reason="root writes into a directory it may not")
def test_a_write_the_filesystem_refuses_after_the_read_is_reported_not_raised(
    tree: Path, run_id: str
) -> None:
    """`fsutil.write` renames a temp file into place, so a read-only directory refuses it."""
    with deny(tree, writes_only=True):
        assert undo(tree, run_id).exit_code == 4
    assert {one["reason"] for one in document(tree, run_id)["files"]} == {"unreadable"}


def test_the_vocabulary_is_closed_and_every_member_is_reachable() -> None:
    """`outside_root` needs a forged row, but stays: the guard has one vocabulary for both ends."""
    expected = {
        "hash_mismatch",
        "missing",
        "not_a_file",
        "outside_root",
        "snapshot_unusable",
        "symlink",
        "unreadable",
    }
    assert set(UNDO_SKIPS) == expected


@pytest.mark.skipif(AS_ROOT, reason="root writes into a directory it may not")
def test_the_document_cannot_be_written_and_the_command_says_which_half_happened(
    tree: Path, run_id: str
) -> None:
    """Files back, `undo.json` not: exit 1, and the message says the repository did change."""
    with deny(tree / ".obelize" / "runs" / run_id, writes_only=True):
        result = undo(tree, run_id)
    assert result.exit_code == 1
    assert "The files were put back, but what happened to each was not saved." in result.output
    assert (tree / "app.py").read_text(encoding="utf-8") == LEGACY


def test_undoing_a_run_that_wrote_nothing_is_not_a_success(tree: Path, run_id: str) -> None:
    """`0` would tell a script the pre-migration state is restored, but nothing was put back."""
    subprocess.run(["git", "-C", str(tree), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tree), "-c", "commit.gpgsign=false", "commit", "-qm", "after"],
        check=True,
    )
    again = runner.invoke(app, ["fix", "--repo", str(tree), "--pack", PACK, "--apply"])
    assert again.exit_code == 4, again.output
    empty = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    assert empty != run_id
    result = undo(tree, empty)
    assert result.exit_code == 4
    assert document(tree, empty)["files"] == []
    assert "0 of 0 file(s) put back." in result.output


# A checkout can carry `.obelize/`. Each case links one piece of a run folder outside the
# repository, and the outside must stay byte-identical.


def _outside(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    return outside


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_a_run_folder_that_is_a_link_is_refused(tree: Path, run_id: str, tmp_path: Path) -> None:
    outside = _outside(tmp_path)
    folder = tree / ".obelize" / "runs" / run_id
    folder.rename(outside / run_id)
    link(folder, outside / run_id)
    before = _snapshot(outside)

    result = undo(tree, run_id)

    assert result.exit_code == 2, result.output
    assert "symbolic link" in result.output
    assert _snapshot(outside) == before


def test_an_index_that_is_a_link_is_refused(tree: Path, run_id: str, tmp_path: Path) -> None:
    outside = _outside(tmp_path)
    index = tree / ".obelize" / "runs" / run_id / "run.json"
    index.rename(outside / "run.json")
    index.symlink_to(outside / "run.json")
    before = _snapshot(outside)

    result = undo(tree, run_id)

    assert result.exit_code == 2, result.output
    assert _snapshot(outside) == before


def test_an_undo_record_that_is_a_link_is_replaced_and_not_followed(
    tree: Path, run_id: str, tmp_path: Path
) -> None:
    outside = _outside(tmp_path)
    (outside / "victim.txt").write_text("somebody's file\n", encoding="utf-8")
    (tree / ".obelize" / "runs" / run_id / "undo.json").symlink_to(outside / "victim.txt")

    result = undo(tree, run_id)

    assert result.exit_code == 0, result.output
    assert (outside / "victim.txt").read_text(encoding="utf-8") == "somebody's file\n"
    written = tree / ".obelize" / "runs" / run_id / "undo.json"
    assert not written.is_symlink()
    assert json.loads(written.read_text(encoding="utf-8"))["run_id"] == run_id


def test_a_snapshot_reached_through_a_link_is_not_read(
    tree: Path, run_id: str, tmp_path: Path
) -> None:
    """Read through a link, a copy would write an outside file's contents into a tracked one."""
    outside = _outside(tmp_path)
    before = tree / ".obelize" / "runs" / run_id / "snapshots" / "before"
    before.rename(outside / "before")
    link(before, outside / "before")
    migrated = (tree / "app.py").read_bytes()

    result = undo(tree, run_id)

    assert result.exit_code == 4, result.output
    assert row(tree, run_id, "app.py")["reason"] == "snapshot_unusable"
    assert (tree / "app.py").read_bytes() == migrated


def test_a_recorded_name_the_system_reserves_is_skipped_before_it_is_read(
    tree: Path, nested_run: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' answer, stubbed: there a forged `aux.py` row would read a device. The stub answers
    for the whole path only, since a directory's name can be one too."""
    opened: list[Path] = []
    read = fsutil.read

    def spy(path: Path) -> bytes:
        opened.append(path)
        return read(path)

    monkeypatch.setattr(files, "reserved", lambda path: path == "pkg/app.py")
    monkeypatch.setattr(fsutil, "read", spy)
    undo(tree, nested_run)
    assert row(tree, nested_run, "pkg/app.py")["reason"] == "outside_root"
    assert tree / "pkg" / "app.py" not in opened
