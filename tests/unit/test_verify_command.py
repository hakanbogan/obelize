"""`obelize verify`: the runs it refuses to be pointed at, and what it rewrites.

A bad run id, missing folder, unreadable index or run with no after-state is exit 2, not a verdict.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from obelize import fsutil
from obelize.cli import app
from obelize.evidence import report
from obelize.native import files
from platforms import AS_ROOT, PYTHON, deny, link, quoted, reports_held_as_on_windows

runner = CliRunner()

PACK = "gemini/google-generativeai-to-google-genai"
QUIET = f"{PYTHON} -c pass"
NOISY = f"{PYTHON} -c \"print('ok')\""

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


def nest(tree: Path) -> None:
    """Move the legacy file one directory down, so a recorded path holds a directory."""
    (tree / "pkg").mkdir()
    subprocess.run(["git", "-C", str(tree), "mv", "app.py", "pkg/app.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tree), "-c", "commit.gpgsign=false", "commit", "-qm", "nested"],
        check=True,
    )


def applied(tree: Path) -> str:
    """Run `fix --apply` and return its run id."""
    result = runner.invoke(
        app, ["fix", "--repo", str(tree), "--pack", PACK, "--apply", "--verify", QUIET]
    )
    assert result.exit_code == 0, result.output
    return (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()


def planned(tree: Path) -> str:
    result = runner.invoke(app, ["fix", "--repo", str(tree), "--pack", PACK])
    assert result.exit_code == 0, result.output
    return (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()


def verify(tree: Path, run_id: str, *extra: str) -> Result:
    return runner.invoke(app, ["verify", "--repo", str(tree), "--run", run_id, *extra])


def folder(tree: Path, run_id: str) -> Path:
    return tree / ".obelize" / "runs" / run_id


def test_a_run_id_that_is_not_one_is_refused_before_it_becomes_a_path(tree: Path) -> None:
    """The id is checked as a shape, not left to a later containment check."""
    result = verify(tree, "../../etc")
    assert result.exit_code == 2
    assert "is not a run id of the form" in result.output
    assert ".obelize/latest holds the most recent one." in result.output


def test_a_run_that_is_not_there_says_so(tree: Path) -> None:
    result = verify(tree, "20260101T000000Z-deadbeef")
    assert result.exit_code == 2
    assert "there is no run" in result.output


def test_an_index_that_cannot_be_read_and_one_that_is_not_a_record(tree: Path) -> None:
    run_id = applied(tree)
    index = folder(tree, run_id) / "run.json"
    index.write_text("{not json", encoding="utf-8")
    assert "is not a run record" in verify(tree, run_id).output
    index.write_text('{"run_id": "nope"}', encoding="utf-8")
    assert "is not a run record" in verify(tree, run_id).output
    index.unlink()
    index.mkdir()
    result = verify(tree, run_id)
    assert result.exit_code == 2
    assert "cannot be read" in result.output


def test_a_dry_run_has_no_after_state_to_verify(tree: Path) -> None:
    result = verify(tree, planned(tree))
    assert result.exit_code == 2
    assert "is a 'plan' run" in result.output
    assert "Run obelize fix --apply to produce one." in result.output


def test_an_apply_that_wrote_nothing_has_no_hash_to_check_against(tree: Path) -> None:
    """The second apply over a migrated tree: `file_edits` is empty."""
    applied(tree)
    subprocess.run(["git", "-C", str(tree), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tree), "-c", "commit.gpgsign=false", "commit", "-qm", "after"],
        check=True,
    )
    again = runner.invoke(app, ["fix", "--repo", str(tree), "--pack", PACK, "--apply"])
    assert again.exit_code == 4
    result = verify(tree, (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip())
    assert result.exit_code == 2
    assert "wrote no file" in result.output


def test_a_repo_that_is_not_a_directory_is_a_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["verify", "--repo", str(tmp_path / "gone"), "--run", "20260101T000000Z-deadbeef"]
    )
    assert result.exit_code == 2


def test_no_command_configured_is_a_verdict_and_not_a_usage_error(tree: Path) -> None:
    """`6`: the patch is there and nothing checked it."""
    run_id = applied(tree)
    result = verify(tree, run_id)
    assert result.exit_code == 6
    record = json.loads((folder(tree, run_id) / "run.json").read_text(encoding="utf-8"))
    assert (record["verify"]["status"], record["verify"]["reason"]) == (
        "not_run",
        "no_verify_commands",
    )


def test_an_apply_that_verified_nothing_can_be_verified_later(tree: Path) -> None:
    """Its folder has no `verify/` for the record to go in until this run makes one."""
    result = runner.invoke(app, ["fix", "--repo", str(tree), "--pack", PACK, "--apply"])
    assert result.exit_code == 6, result.output
    run_id = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    assert not (folder(tree, run_id) / "verify").exists()
    result = verify(tree, run_id, "--verify", QUIET)
    assert result.exit_code == 0, result.output
    record = json.loads((folder(tree, run_id) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["status"] == "pass"
    index = folder(tree, run_id) / "verify" / "verify.json"
    assert json.loads(index.read_text(encoding="utf-8")) == record["verify"]


def test_a_command_the_repository_asked_for_is_refused_in_a_non_interactive_run(
    tree: Path, tmp_path: Path
) -> None:
    """Commands come from `.obelize.yml` through the ladder, never from the run folder."""
    run_id = applied(tree)
    (tree / ".obelize.yml").write_text("verify:\n  commands:\n    - pytest -q\n", encoding="utf-8")
    result = verify(tree, run_id, "--non-interactive")
    assert result.exit_code == 5
    record = json.loads((folder(tree, run_id) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["reason"] == "policy_refused"


def test_an_allowlist_entry_that_cannot_run_is_a_usage_error(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read only once the repository asks for a command, so after the run is found."""
    run_id = applied(tree)
    (tree / ".obelize.yml").write_text("verify:\n  commands:\n    - pytest -q\n", encoding="utf-8")
    home = tmp_path / "home"
    (home / "obelize").mkdir(parents=True)
    (home / "obelize" / "config.yml").write_text(
        "verify:\n  allow:\n    - 'pytest | tee log'\n", encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    record = (folder(tree, run_id) / "run.json").read_bytes()
    result = verify(tree, run_id, "--non-interactive")
    assert result.exit_code == 2, result.output
    assert "runs without a shell" in result.output
    assert (folder(tree, run_id) / "run.json").read_bytes() == record


def test_the_timeout_flag_stops_a_command_that_outlasts_it(tree: Path) -> None:
    run_id = applied(tree)
    slow = f'{PYTHON} -c "import time; time.sleep(5)"'
    result = verify(tree, run_id, "--verify", slow, "--timeout", "1")
    assert result.exit_code == 6, result.output
    record = json.loads((folder(tree, run_id) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["reason"] == "timeout"


def test_a_report_that_cannot_be_deleted_does_not_stop_the_verdict_being_recorded(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reports' temporary folder is left behind, which is the control: its cleanup failed."""
    run_id = applied(tree)
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_one.py").write_text("def test_one():\n    assert True\n", encoding="utf-8")
    temporary = tmp_path / "temporary"
    reports_held_as_on_windows(monkeypatch, temporary)
    command = f"{PYTHON} -m pytest -q {quoted(suite)}"
    result = verify(tree, run_id, "--verify", command)
    assert result.exit_code == 0, result.output
    record = json.loads((folder(tree, run_id) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["commands"][0]["command"] == command
    assert (folder(tree, run_id) / "verify" / "after" / "1.junit.xml").exists()
    assert len(list(temporary.glob("*/1.junit.xml"))) == 1


def test_a_report_that_cannot_be_read_is_left_alone_rather_than_failing_the_run(
    tree: Path,
) -> None:
    run_id = applied(tree)
    (folder(tree, run_id) / "REPORT.md").unlink()
    assert verify(tree, run_id, "--verify", QUIET).exit_code == 0
    assert not (folder(tree, run_id) / "REPORT.md").exists()


def test_a_file_that_is_gone_is_a_tree_that_changed(tree: Path) -> None:
    run_id = applied(tree)
    (tree / "app.py").unlink()
    result = verify(tree, run_id, "--verify", QUIET)
    assert result.exit_code == 6
    record = json.loads((folder(tree, run_id) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["reason"] == "tree_changed"


def test_a_recorded_name_the_system_reserves_is_a_changed_tree_before_it_is_read(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' answer, stubbed: there a forged `aux.py` row would read a device. The stub answers
    for the whole path only, since a directory's name can be one too."""
    nest(tree)
    run_id = applied(tree)
    opened: list[Path] = []
    read = fsutil.read

    def spy(path: Path) -> bytes:
        opened.append(path)
        return read(path)

    monkeypatch.setattr(files, "reserved", lambda path: path == "pkg/app.py")
    monkeypatch.setattr(fsutil, "read", spy)
    assert verify(tree, run_id, "--verify", QUIET).exit_code == 6
    record = json.loads((folder(tree, run_id) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["reason"] == "tree_changed"
    assert tree / "pkg" / "app.py" not in opened


@pytest.mark.skipif(AS_ROOT, reason="root writes into a directory it may not")
def test_a_folder_that_cannot_be_rewritten_exits_one(tree: Path) -> None:
    """A verification whose result is only on a terminal is a failure of the run."""
    result = runner.invoke(
        app, ["fix", "--repo", str(tree), "--pack", PACK, "--apply", "--verify", NOISY]
    )
    assert result.exit_code == 0, result.output
    run_id = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    # `verify/`, not the run folder: `run.json` stays replaceable, but no name can be added to
    # `verify/`. POSIX also refuses removing `verify/after/`, which holds the noisy log; Windows
    # removes it and refuses the first name written back.
    locked = folder(tree, run_id) / "verify"
    assert (locked / "after" / "1.log").is_file()
    with deny(locked, writes_only=True):
        result = verify(tree, run_id, "--verify", QUIET)
    assert result.exit_code == 1
    assert "could not be recorded" in result.output


def test_the_superseding_note_replaces_itself_rather_than_stacking(tree: Path) -> None:
    run_id = applied(tree)
    assert verify(tree, run_id, "--verify", QUIET).exit_code == 0
    once = (folder(tree, run_id) / "REPORT.md").read_text(encoding="utf-8")
    assert verify(tree, run_id, "--verify", QUIET).exit_code == 0
    twice = (folder(tree, run_id) / "REPORT.md").read_text(encoding="utf-8")
    assert twice.count(report.SUPERSEDED) == 1
    assert once.count(report.SUPERSEDED) == 1
    assert twice.split(report.SUPERSEDED)[0] == once.split(report.SUPERSEDED)[0]


@pytest.mark.parametrize(
    ("command", "verdict"),
    [
        (QUIET, "`pass`"),
        (f'{PYTHON} -c "raise SystemExit(1)"', "`fail` (`command_failed`)"),
    ],
    ids=["pass", "fail"],
)
def test_the_superseding_note_names_the_new_verdict_and_its_reason(
    tree: Path, command: str, verdict: str
) -> None:
    run_id = applied(tree)
    verify(tree, run_id, "--verify", command)
    note = (folder(tree, run_id) / "REPORT.md").read_text(encoding="utf-8")
    (said,) = [line for line in note.splitlines() if line.startswith("`obelize verify` checked")]
    assert said.split(": ", 1)[1].startswith(f"{verdict}. The section above")


@pytest.mark.parametrize(
    ("first", "configured", "reason", "said"),
    [
        (
            ["--verify", QUIET],
            False,
            None,
            ". The Baseline section above still shows the tests run before the change.",
        ),
        ([], False, "no_verify_commands", ". No tests ran before the change."),
        (["--non-interactive"], True, "policy_refused", ". No tests ran before the change."),
    ],
    ids=["baseline", "no_command", "refused"],
)
def test_the_superseding_note_says_whether_tests_ran_before_the_change(
    tree: Path, first: list[str], configured: bool, reason: str | None, said: str
) -> None:
    """Twice: a re-verified record carries no baseline either way. Control: `QUIET` prints
    nothing, so no case leaves a `verify/baseline/` the note could point at."""
    if configured:
        (tree / ".obelize.yml").write_text(
            "verify:\n  commands:\n    - pytest -q\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(tree), "add", ".obelize.yml"], check=True)
        subprocess.run(
            ["git", "-C", str(tree), "-c", "commit.gpgsign=false", "commit", "-qm", "configure"],
            check=True,
        )
    runner.invoke(app, ["fix", "--repo", str(tree), "--pack", PACK, "--apply", *first])
    run_id = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    record = json.loads((folder(tree, run_id) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["reason"] == reason
    assert not (folder(tree, run_id) / "verify" / "baseline").exists()
    for _ in range(2):
        assert verify(tree, run_id, "--verify", QUIET).exit_code == 0
        note = (folder(tree, run_id) / "REPORT.md").read_text(encoding="utf-8")
        (line,) = [one for one in note.splitlines() if one.startswith("`obelize verify` checked")]
        assert line.endswith(f"hold the new one{said}"), line


def test_the_pointer_is_not_moved_because_no_run_was_created(tree: Path) -> None:
    run_id = applied(tree)
    before = sorted((tree / ".obelize" / "runs").iterdir())
    assert verify(tree, run_id, "--verify", QUIET).exit_code == 0
    assert sorted((tree / ".obelize" / "runs").iterdir()) == before
    assert (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip() == run_id


def test_a_quiet_re_verification_leaves_no_log_from_the_noisy_one(tree: Path) -> None:
    """`verify/after/` is replaced, not merged, so no file remains that the index does not name."""
    result = runner.invoke(
        app, ["fix", "--repo", str(tree), "--pack", PACK, "--apply", "--verify", NOISY]
    )
    assert result.exit_code == 0, result.output
    run_id = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    after = folder(tree, run_id) / "verify" / "after"
    assert sorted(path.name for path in after.iterdir()) == ["1.log"]
    assert verify(tree, run_id, "--verify", QUIET).exit_code == 0
    # Removed whole: only a phase that produces a file recreates it.
    assert not after.exists()
    # The baseline was not re-measured, so it stays.
    assert (folder(tree, run_id) / "verify" / "baseline" / "1.log").is_file()


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_a_verification_folder_that_is_a_link_is_not_emptied(tree: Path, tmp_path: Path) -> None:
    """Re-verification empties `verify/after/`; through a link it would empty an outside one."""
    run_id = applied(tree)
    outside = tmp_path / "outside"
    (outside / "after").mkdir(parents=True)
    (outside / "after" / "keep.txt").write_text("keep\n", encoding="utf-8")
    verification = folder(tree, run_id) / "verify"
    shutil.rmtree(verification)
    link(verification, outside)
    before = _snapshot(outside)

    result = verify(tree, run_id, "--verify", QUIET)

    assert result.exit_code == 1, result.output
    assert "symbolic link" in result.output
    assert _snapshot(outside) == before


def test_a_report_that_is_a_link_is_neither_read_nor_written(tree: Path, tmp_path: Path) -> None:
    run_id = applied(tree)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim.md").write_text("somebody's notes\n", encoding="utf-8")
    linked = folder(tree, run_id) / "REPORT.md"
    linked.unlink()
    linked.symlink_to(outside / "victim.md")

    verify(tree, run_id, "--verify", QUIET)

    assert (outside / "victim.md").read_text(encoding="utf-8") == "somebody's notes\n"
    # Left alone: read through the link, the outside text would be copied into the run folder.
    assert linked.is_symlink()
