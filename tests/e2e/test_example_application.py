"""The whole flow over `examples/gemini-legacy-app`, the one repository written as an application.

Nothing is written, deliberately (ADR-031 D11): `summarize.py` and `conversation.py` run on the
`configure` in `summarizer/config.py`; more automation is a rule change, not a test update.
The evidence assertions mirror `.github/workflows/e2e.yml`, which runs from a built wheel.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from obelize.cli import app
from platforms import PYTHON

pytestmark = pytest.mark.e2e

runner = CliRunner()

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "gemini-legacy-app"
PACK = "gemini/google-generativeai-to-google-genai"

# Needs neither SDK; given so the record shows a command an apply that wrote nothing never runs.
QUIET = f"{PYTHON} -c pass"

# The eleven rows that can never migrate, the two in `config.py` waiting on them, and the pin.
WITHHELD = 14


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *arguments],
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def app_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A committed copy: apply refuses a dirty tree."""
    work = tmp_path_factory.mktemp("e2e") / "app"
    shutil.copytree(EXAMPLE, work)
    git(work, "init", "-q", "-b", "work")
    git(work, "config", "user.name", "obelize tests")
    git(work, "config", "user.email", "tests@obelize.invalid")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "the application before the migration")
    return work


def invoke(work: Path, *arguments: str) -> Result:
    return runner.invoke(app, [*arguments, "--repo", str(work)], catch_exceptions=False)


def latest(work: Path) -> Path:
    run_id = (work / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    return work / ".obelize" / "runs" / run_id


def record(folder: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def migrated(app_repo: Path) -> dict[str, Any]:
    """`scan`, `fix`, `fix --apply` in one module-scoped run: each must read what the last wrote."""
    scanned = invoke(app_repo, "scan", "--pack", PACK, "--json")
    planned = invoke(app_repo, "fix", "--pack", PACK)
    plan_folder = latest(app_repo)
    applied = invoke(app_repo, "fix", "--pack", PACK, "--apply", "--verify", QUIET)
    folder = latest(app_repo)
    return {
        "work": app_repo,
        "scanned": scanned,
        "planned": planned,
        "plan": plan_folder,
        "applied": applied,
        "folder": folder,
        "run": record(folder),
    }


def test_the_scan_finds_the_application_and_writes_nothing(migrated: dict[str, Any]) -> None:
    """The scan grades one file at a time, so three rows are `eligible` that the run withholds."""
    assert migrated["scanned"].exit_code == 0
    document = json.loads(migrated["scanned"].stdout)
    assert document["counts"]["findings"] == 17
    assert document["counts"]["eligible"] == 3


def test_the_dry_run_plans_no_edit(migrated: dict[str, Any]) -> None:
    """ADR-011 D3: a plan exits `0` however much it leaves for a person."""
    assert migrated["planned"].exit_code == 0
    plan = json.loads((migrated["plan"] / "plan.json").read_text(encoding="utf-8"))
    assert plan["files"] == []
    assert record(migrated["plan"])["file_edits"] == []
    assert record(migrated["plan"])["mode"] == "plan"


def test_the_apply_writes_nothing_and_says_why(migrated: dict[str, Any]) -> None:
    """`4`, not `0`: fourteen rows are outstanding, and the two in `config.py` name the reason."""
    assert migrated["applied"].exit_code == 4
    run = migrated["run"]
    assert run["mode"] == "apply"
    assert run["file_edits"] == []
    assert run["counts"]["auto"] == 0
    assert run["idempotent"] is True
    assert run["refused"] == []
    assert len(run["withheld"]) == WITHHELD
    held = [
        (row["line"], row["bail"], row["caused_by"])
        for row in run["withheld"]
        if row["path"] == "summarizer/config.py"
    ]
    assert held == [
        (9, "file_not_fully_migrated", ["configure_consumed_elsewhere"]),
        (22, "configure_consumed_elsewhere", None),
    ]


def test_the_tree_was_clean_when_obelize_looked_at_it(migrated: dict[str, Any]) -> None:
    assert migrated["run"]["git_dirty"] is False


def test_nothing_is_verified_because_nothing_was_written(migrated: dict[str, Any]) -> None:
    """A command was given, and an apply that wrote no file never runs it."""
    verify = migrated["run"]["verify"]
    assert verify["status"] == "not_run"
    assert verify["reason"] == "no_changes_to_verify"
    assert verify["commands"] == []
    assert verify["baseline"] is None


def test_every_artefact_the_mode_owes_is_in_the_folder(migrated: dict[str, Any]) -> None:
    """No snapshots: they are kept for the files a run wrote, and this one wrote none."""
    for name in (
        "findings.json",
        "plan.json",
        "patch.diff",
        "pack.yaml",
        "pack.sha256",
        "REPORT.md",
        "run.json",
    ):
        assert (migrated["folder"] / name).is_file(), name
    assert not (migrated["folder"] / "snapshots").exists()


def test_the_application_is_exactly_what_it_was(migrated: dict[str, Any]) -> None:
    work = migrated["work"]
    subprocess.run(["git", "-C", str(work), "diff", "--exit-code"], check=True)
    status = subprocess.run(
        ["git", "-C", str(work), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert status.stdout == ""


def test_a_second_apply_changes_nothing_and_says_so(migrated: dict[str, Any]) -> None:
    """`4`, not `5`: the app's `.obelize.yml` names a command, but a no-op run never consults it."""
    work = migrated["work"]
    again = invoke(work, "fix", "--pack", PACK, "--apply", "--non-interactive")
    assert again.exit_code == 4, again.output
    second = record(latest(work))
    assert second["idempotent"] is True
    assert second["file_edits"] == []
    assert second["verify"]["reason"] == "no_changes_to_verify"
    subprocess.run(["git", "-C", str(work), "diff", "--exit-code"], check=True)
