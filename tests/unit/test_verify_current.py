"""`obelize verify --current`: the verification run on the tree as it stands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner, Result

from obelize.cli import app
from obelize.models import VerifyRecord
from platforms import PYTHON
from support import committed

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

PACK = "gemini/google-generativeai-to-google-genai"
PASS = f"{PYTHON} -c pass"
FAIL = f'{PYTHON} -c "raise SystemExit(1)"'

LEGACY = """import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
"""

PLAIN = "def add(left, right):\n    return left + right\n"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return committed(
        tmp_path / "repo", {"app.py": LEGACY, "requirements.txt": "google-generativeai==0.8.6\n"}
    )


def _fix(tree: Path, *extra: str, code: int = 0) -> str:
    result = runner.invoke(app, ["fix", "--repo", str(tree), "--pack", PACK, *extra])
    assert result.exit_code == code, result.output
    return (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()


def _verify(tree: Path, run_id: str, *extra: str) -> Result:
    return runner.invoke(app, ["verify", "--repo", str(tree), "--run", run_id, *extra])


def _record(tree: Path, run_id: str) -> dict[str, object]:
    path = tree / ".obelize" / "runs" / run_id / "run.json"
    loaded: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def test_an_edited_file_is_a_tree_change_without_current_and_a_listed_file_with_it(
    tree: Path,
) -> None:
    run_id = _fix(tree, "--apply", "--verify", PASS)
    (tree / "app.py").write_text(PLAIN, encoding="utf-8")
    refused = _verify(tree, run_id, "--verify", PASS)
    assert refused.exit_code == 6
    assert "tree_changed" in refused.stdout
    checked = _verify(tree, run_id, "--verify", PASS, "--current")
    assert checked.exit_code == 0, checked.output
    assert "The tree differs from what the run wrote in 1 file(s):\n  app.py\n" in checked.stdout
    verify = _record(tree, run_id)["verify"]
    assert verify["status"] == "pass"  # type: ignore[index]
    assert verify["edited"] == ["app.py"]  # type: ignore[index]


def test_current_runs_the_commands_on_the_tree_as_it_is(tree: Path) -> None:
    run_id = _fix(tree, "--apply", "--verify", PASS)
    (tree / "app.py").write_text(PLAIN, encoding="utf-8")
    failing = _verify(tree, run_id, "--verify", FAIL, "--current")
    assert failing.exit_code == 3
    assert _record(tree, run_id)["verify"]["status"] == "fail"  # type: ignore[index]


def test_a_tree_nobody_touched_lists_no_file(tree: Path) -> None:
    run_id = _fix(tree, "--apply", "--verify", PASS)
    checked = _verify(tree, run_id, "--verify", PASS, "--current")
    assert checked.exit_code == 0
    assert "differs" not in checked.stdout
    assert _record(tree, run_id)["verify"]["edited"] == []  # type: ignore[index]


def test_a_written_file_that_is_gone_is_listed(tree: Path) -> None:
    run_id = _fix(tree, "--apply", "--verify", PASS)
    (tree / "app.py").unlink()
    checked = _verify(tree, run_id, "--verify", PASS, "--current")
    assert checked.exit_code == 0
    assert _record(tree, run_id)["verify"]["edited"] == ["app.py"]  # type: ignore[index]


def test_the_report_says_the_tree_had_changed(tree: Path) -> None:
    run_id = _fix(tree, "--apply", "--verify", PASS)
    (tree / "app.py").write_text(PLAIN, encoding="utf-8")
    _verify(tree, run_id, "--verify", PASS, "--current")
    report = (tree / ".obelize" / "runs" / run_id / "REPORT.md").read_text(encoding="utf-8")
    assert "The tree had changed since the run in 1 file(s) it wrote." in report


def test_a_run_that_wrote_no_file_can_be_checked_with_current_and_only_with_it(
    tmp_path: Path,
) -> None:
    tree = committed(tmp_path / "repo", {"plain.py": PLAIN})
    run_id = _fix(tree, "--apply", "--verify", PASS, code=4)
    refused = _verify(tree, run_id, "--verify", PASS)
    assert refused.exit_code == 2
    assert "--current checks the tree as it stands" in refused.output
    checked = _verify(tree, run_id, "--verify", PASS, "--current")
    assert checked.exit_code == 0, checked.output
    assert _record(tree, run_id)["verify"]["status"] == "pass"  # type: ignore[index]


def test_a_dry_run_has_no_after_state_even_with_current(tree: Path) -> None:
    run_id = _fix(tree)
    result = _verify(tree, run_id, "--verify", PASS, "--current")
    assert result.exit_code == 2
    assert "is a 'plan' run" in result.output


def test_a_baseline_that_failed_still_settles_the_run(tree: Path) -> None:
    run_id = _fix(tree, "--apply", "--verify", FAIL, code=6)
    before = (tree / ".obelize" / "runs" / run_id / "run.json").read_bytes()
    result = _verify(tree, run_id, "--verify", PASS, "--current")
    assert result.exit_code == 6
    assert "Nothing was re-run" in result.stdout
    assert (tree / ".obelize" / "runs" / run_id / "run.json").read_bytes() == before


def test_current_with_json_prints_the_record_it_wrote(tree: Path) -> None:
    run_id = _fix(tree, "--apply", "--verify", PASS)
    (tree / "app.py").write_text(PLAIN, encoding="utf-8")
    result = _verify(tree, run_id, "--verify", PASS, "--current", "--json")
    written = (tree / ".obelize" / "runs" / run_id / "run.json").read_text(encoding="utf-8")
    assert result.stdout == written
    assert json.loads(result.stdout)["verify"]["edited"] == ["app.py"]


def test_the_files_a_verification_names_are_sorted_and_unique() -> None:
    row = {"status": "not_run", "reason": "no_verify_commands"}
    assert VerifyRecord(**row, edited=("a.py", "b.py")).edited == ("a.py", "b.py")
    with pytest.raises(ValidationError, match="edited"):
        VerifyRecord(**row, edited=("b.py", "a.py"))
