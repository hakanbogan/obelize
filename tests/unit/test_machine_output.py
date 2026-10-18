"""What a CI step or an agent reads: SARIF, `--fail-on`, and `--json` on verify and undo."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner, Result

from obelize import __version__
from obelize.cli import app
from obelize.evidence import sarif
from obelize.models import BAIL_ACTIONS, Finding, PackRef
from platforms import PYTHON
from support import committed

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

PACK = "gemini/google-generativeai-to-google-genai"
QUIET = f"{PYTHON} -c pass"

LEGACY = """import google.generativeai as genai

genai.configure(api_key="k")
MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return committed(
        tmp_path / "repo", {"app.py": LEGACY, "requirements.txt": "google-generativeai==0.8.6\n"}
    )


def _scan(tree: Path, *extra: str) -> Result:
    return runner.invoke(app, ["scan", "--repo", str(tree), "--pack", PACK, *extra])


def _folder(tree: Path) -> Path:
    latest = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    return tree / ".obelize" / "runs" / latest


def _row(**fields: Any) -> Finding:
    base: dict[str, Any] = {
        "path": "app.py",
        "line": 3,
        "column": 0,
        "kind": "call",
        "confidence_reason": "direct_import_resolved",
        "symbol": "google.generativeai.configure",
        "scan_status": "eligible",
    }
    return Finding(**{**base, **fields})


# SARIF.


def test_sarif_is_a_2_1_0_document_with_a_result_per_finding_that_is_not_context(
    tree: Path,
) -> None:
    result = _scan(tree, "--sarif")
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["version"] == "2.1.0"
    (run,) = document["runs"]
    assert run["tool"]["driver"]["name"] == "obelize"
    assert run["tool"]["driver"]["version"] == __version__
    findings = json.loads(_scan(tree, "--json").stdout)["findings"]
    expected = [row for row in findings if row["scan_status"] != "not_a_usage"]
    assert len(run["results"]) == len(expected) > 0
    ids = [rule["id"] for rule in run["tool"]["driver"]["rules"]]
    assert ids == sorted(ids)
    for found, row in zip(run["results"], expected, strict=True):
        place = found["locations"][0]["physicalLocation"]
        assert place["artifactLocation"]["uri"] == row["path"]
        assert place["region"] == {"startLine": row["line"], "startColumn": row["column"] + 1}
        assert ids[found["ruleIndex"]] == found["ruleId"] == (row["bail"] or "eligible")


def test_sarif_names_the_packs_it_was_made_with(tree: Path) -> None:
    (run,) = json.loads(_scan(tree, "--sarif").stdout)["runs"]
    assert [pack["id"] for pack in run["properties"]["packs"]] == [PACK]


def test_two_scans_of_one_input_print_the_same_sarif(tree: Path) -> None:
    assert _scan(tree, "--sarif").stdout == _scan(tree, "--sarif").stdout


def test_sarif_prints_the_document_alone_and_says_where_the_evidence_went_on_stderr(
    tree: Path,
) -> None:
    result = _scan(tree, "--sarif")
    assert result.stdout.startswith("{")
    assert result.stdout.endswith("}\n")
    assert f"Evidence: {tree}" in result.stderr


def test_json_and_sarif_each_replace_the_table(tree: Path) -> None:
    result = _scan(tree, "--json", "--sarif")
    assert result.exit_code == 2
    assert "pass one" in result.output
    assert not (tree / ".obelize" / "runs").exists()


def test_a_finding_obelize_can_write_is_a_note_and_one_it_withholds_is_a_warning() -> None:
    withheld = _row(
        line=9,
        scan_status="needs_review",
        bail="usage_unmapped",
    )
    text = sarif.document([_row(), withheld])
    (run,) = json.loads(text)["runs"]
    first, second = run["results"]
    assert (first["ruleId"], first["level"]) == ("eligible", "note")
    assert (second["ruleId"], second["level"]) == ("usage_unmapped", "warning")
    assert BAIL_ACTIONS["usage_unmapped"] in second["message"]["text"]
    assert "`google.generativeai.configure`" in first["message"]["text"]


def test_an_unsupported_finding_is_an_error() -> None:
    row = _row(scan_status="unsupported", bail="attribute_removed")
    (run,) = json.loads(sarif.document([row]))["runs"]
    assert run["results"][0]["level"] == "error"


def test_the_codes_that_held_a_file_back_are_in_the_message() -> None:
    row = _row(
        scan_status="needs_review",
        bail="file_not_fully_migrated",
        caused_by=("usage_unmapped",),
    )
    (run,) = json.loads(sarif.document([row]))["runs"]
    assert "Held back by: usage_unmapped." in run["results"][0]["message"]["text"]


def test_prose_and_context_are_not_results() -> None:
    mention = _row(
        kind="text_mention",
        confidence_reason="string_or_comment_mention",
        scan_status="not_a_usage",
    )
    (run,) = json.loads(sarif.document([mention]))["runs"]
    assert run["results"] == []
    assert run["tool"]["driver"]["rules"] == []


def test_the_packs_are_recorded_as_a_property() -> None:
    pack = PackRef(id="demo/legacy-to-modern", version="1.0.0", sha256="0" * 64)
    (run,) = json.loads(sarif.document([], [pack]))["runs"]
    assert run["properties"]["packs"] == [
        {"id": "demo/legacy-to-modern", "version": "1.0.0", "sha256": "0" * 64}
    ]


# --fail-on.


def _statuses(tree: Path) -> set[str]:
    return {row["scan_status"] for row in json.loads(_scan(tree, "--json").stdout)["findings"]}


def test_a_scan_without_fail_on_exits_zero_whatever_it_finds(tree: Path) -> None:
    assert _statuses(tree) - {"not_a_usage"}
    assert _scan(tree).exit_code == 0
    assert json.loads((_folder(tree) / "run.json").read_text(encoding="utf-8"))["exit_code"] == 0


@pytest.mark.parametrize("status", ["eligible", "needs_review", "unsupported"])
def test_fail_on_exits_four_exactly_when_a_finding_has_a_status_named(
    tree: Path, status: str
) -> None:
    present = status in _statuses(tree)
    result = _scan(tree, "--fail-on", status)
    assert result.exit_code == (4 if present else 0), result.output
    recorded = json.loads((_folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert recorded["exit_code"] == (4 if present else 0)
    assert ("--fail-on" in result.stderr) is present


def test_fail_on_may_be_repeated(tree: Path) -> None:
    assert _scan(tree, "--fail-on", "unsupported", "--fail-on", "eligible").exit_code == 4


def test_fail_on_still_prints_the_document_it_was_asked_for(tree: Path) -> None:
    result = _scan(tree, "--json", "--fail-on", "eligible")
    assert result.exit_code == 4
    assert json.loads(result.stdout)["findings"]


def test_fail_on_names_a_status_a_finding_can_have(tree: Path) -> None:
    result = _scan(tree, "--fail-on", "not_a_usage")
    assert result.exit_code == 2
    assert "--fail-on takes eligible, needs_review, unsupported; got not_a_usage." in (
        result.output
    )
    assert not (tree / ".obelize" / "runs").exists()


# verify --json and undo --json.


def _applied(tree: Path) -> str:
    result = runner.invoke(
        app, ["fix", "--repo", str(tree), "--pack", PACK, "--apply", "--verify", QUIET]
    )
    assert result.exit_code == 0, result.output
    return (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()


def test_verify_json_is_the_run_record_it_wrote(tree: Path) -> None:
    run_id = _applied(tree)
    result = runner.invoke(
        app, ["verify", "--repo", str(tree), "--run", run_id, "--verify", QUIET, "--json"]
    )
    assert result.exit_code == 0, result.output
    written = (tree / ".obelize" / "runs" / run_id / "run.json").read_text(encoding="utf-8")
    assert result.stdout == written
    assert json.loads(result.stdout)["verify"]["status"] == "pass"
    assert f"Evidence: {tree}" in result.stderr


def test_verify_json_keeps_the_exit_code_of_the_verdict(tree: Path) -> None:
    run_id = _applied(tree)
    failing = f'{PYTHON} -c "raise SystemExit(1)"'
    result = runner.invoke(
        app, ["verify", "--repo", str(tree), "--run", run_id, "--verify", failing, "--json"]
    )
    assert result.exit_code == 3
    assert json.loads(result.stdout)["verify"]["status"] == "fail"


def test_undo_json_is_the_undo_record_it_wrote(tree: Path) -> None:
    run_id = _applied(tree)
    result = runner.invoke(app, ["undo", "--repo", str(tree), "--run", run_id, "--json"])
    assert result.exit_code == 0, result.output
    written = (tree / ".obelize" / "runs" / run_id / "undo.json").read_text(encoding="utf-8")
    assert result.stdout == written
    assert {row["outcome"] for row in json.loads(result.stdout)["files"]} == {"reverted"}


def test_undo_json_reports_a_skipped_file_and_exits_four(tree: Path) -> None:
    run_id = _applied(tree)
    (tree / "app.py").write_text("edited = True\n", encoding="utf-8")
    result = runner.invoke(app, ["undo", "--repo", str(tree), "--run", run_id, "--json"])
    assert result.exit_code == 4
    rows = {row["path"]: row for row in json.loads(result.stdout)["files"]}
    assert rows["app.py"]["outcome"] == "skipped"
    assert rows["app.py"]["reason"] == "hash_mismatch"
