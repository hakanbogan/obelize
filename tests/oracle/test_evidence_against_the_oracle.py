"""What a fix run folder records, over five small repositories and six runs.

The key is tests/fixtures/evidence/answers.yaml; its header says what is graded and what is given.
`patch.diff` is graded by `git apply` onto pristine inputs, which must reproduce the driver's bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from obelize import fsutil, gitutil
from obelize.evidence import report, run_dir
from obelize.models import (
    CommandResult,
    Config,
    FindingsDocument,
    PackRef,
    VerifyPhase,
    VerifyResult,
)
from obelize.packs import loader
from obelize.scan import runner, walker
from obelize.transforms import codemod

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "evidence"
BUNDLED = loader.load("gemini/google-generativeai-to-google-genai")
SPEC = loader.to_scan_spec(BUNDLED)
KEY: dict[str, Any] = yaml.safe_load((ROOT / "answers.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["case"]: case for case in KEY["cases"]}

# Pinned so run ids and `run.json` (apart from durations) are identical across test runs.
WHEN = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)

# Reported by the fake verification, never executed; only where its output lands is graded.
COMMAND = "pytest -q"
OUTPUT = "1 passed in 0.04s\n"

# One parameter per run, so a failure names the run, not just the repository.
RUNS = [(name, index) for name in sorted(CASES) for index in range(len(CASES[name]["runs"]))]


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *arguments],
        check=True,
        capture_output=True,
    )


def prepare(work: Path, state: dict[str, Any]) -> None:
    """Commit first, then append the key's edits: `dirty/` must become dirty after a clean tree."""
    if not state.get("init"):
        return
    git(work, "init", "-q", "-b", "work")
    git(work, "config", "user.name", "obelize tests")
    git(work, "config", "user.email", "tests@obelize.invalid")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "the tree before obelize saw it")
    for name, text in (state.get("appended") or {}).items():
        with (work / name).open("a", encoding="utf-8") as handle:
            handle.write(text)


def passed() -> CommandResult:
    """A passing command with stdout, so a log file is written."""
    return CommandResult(
        command=COMMAND,
        source="cli",
        status="pass",
        exit_code=0,
        duration_ms=41,
        output=OUTPUT,
    )


def verdict(spec: dict[str, Any]) -> VerifyResult:
    """The key's verification, stated not run; `RunRecord` refuses a `not_run` with no reason."""
    if spec.get("verification") == "pass_with_baseline":
        return VerifyResult(
            status="pass",
            commands=(passed(),),
            baseline=VerifyPhase(status="pass", commands=(passed(),)),
        )
    if spec["mode"] == "plan":
        return VerifyResult(status="not_run", reason="dry_run")
    return VerifyResult(status="not_run", reason="no_changes_to_verify")


def drive(work: Path, spec: dict[str, Any], index: int) -> dict[str, Any]:
    """One fix run over one repository, from the walk to `.obelize/latest`, without the CLI."""
    config = Config()
    scan = runner.scan(work, config, SPEC, jobs=1)
    selection = walker.walk(work, config)
    wanted = {result.path for result in scan.results} | set(selection.manifests)
    sources = {name: (work / name).read_bytes() for name in sorted(wanted)}
    run = codemod.run(scan, sources, BUNDLED.pack, SPEC)
    plan = run_dir.planned(run, BUNDLED)
    state = gitutil.state(work)

    applied = (
        None
        if spec["mode"] == "plan"
        else fsutil.apply(work, list(plan.changes), allow_dirty=bool(spec.get("allow_dirty")))
    )
    verified = run_dir.verification(verdict(spec))
    record = run_dir.compose_fix(
        run_id=run_dir.new_id(WHEN, f"0000bee{index}"),
        scan=scan,
        run=run,
        plan=plan,
        verified=verified,
        pack=BUNDLED,
        config=config,
        source="defaults",
        git=state,
        argv=("fix", "--apply") if applied is not None else ("fix",),
        applied=applied,
        exit_code=spec["exit_code"],
        started=WHEN,
        finished=WHEN,
        total_ms=10,
        scan_ms=4,
        plan_ms=3,
        apply_ms=2 if applied is not None else None,
        verify_ms=1 if verified.record.status != "not_run" else None,
    )
    findings = FindingsDocument(
        obelize_version=record.obelize_version,
        pack=PackRef(id=BUNDLED.pack.id, version=BUNDLED.pack.pack_version, sha256=BUNDLED.sha256),
        counts=scan.counts,
        findings=scan.findings,
    )
    written = run_dir.write(
        work,
        record,
        findings.model_dump_json(indent=2) + "\n",
        BUNDLED.data,
        report.document(record, scan, run, plan.document),
        run_dir.artefacts(plan, verified, applied),
    )
    return {
        "root": work,
        "folder": written.directory,
        "relative": written.relative,
        "changes": plan.changes,
        "run": json.loads((written.directory / "run.json").read_text(encoding="utf-8")),
        "plan": json.loads((written.directory / "plan.json").read_text(encoding="utf-8")),
        "report": (written.directory / "REPORT.md").read_text(encoding="utf-8"),
        "patch": (written.directory / "patch.diff").read_bytes(),
    }


@pytest.fixture(scope="module")
def corpora(tmp_path_factory: pytest.TempPathFactory) -> dict[str, list[dict[str, Any]]]:
    """Every case in its git state, run once per run the key lists."""
    built: dict[str, list[dict[str, Any]]] = {}
    for name in sorted(CASES):
        work = tmp_path_factory.mktemp("evidence") / name
        shutil.copytree(ROOT / name, work)
        prepare(work, CASES[name].get("git") or {})
        built[name] = [drive(work, spec, index) for index, spec in enumerate(CASES[name]["runs"])]
    return built


def answer(name: str, index: int) -> dict[str, Any]:
    result: dict[str, Any] = CASES[name]["runs"][index]
    return result


def folder(corpora: dict[str, list[dict[str, Any]]], name: str, index: int) -> Path:
    path: Path = corpora[name][index]["folder"]
    return path


def relative(folder: Path, path: Path) -> str:
    return str(path.relative_to(folder).as_posix())


# A data row of a `REPORT.md` table; every such table opens with a line number.
_ROW = re.compile(r"^\| \d+ \|")


def _section(document: str, heading: str) -> str:
    """One `## ` section of the report, up to the next one."""
    return document.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]


def test_the_key_grades_every_case_and_every_case_has_a_row() -> None:
    on_disk = {path.name for path in ROOT.iterdir() if path.is_dir()}
    assert on_disk == set(CASES), sorted(on_disk ^ set(CASES))


def test_the_key_names_an_artefact_list_for_every_mode_the_corpus_runs() -> None:
    exercised = {spec["mode"] for case in CASES.values() for spec in case["runs"]}
    assert exercised <= set(KEY["artefacts"])
    assert exercised == {"plan", "apply"}, "the scan mode is graded by its own corpus"


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_the_record_says_what_the_run_was_asked_to_do(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """`mode` is the request and not the outcome: a refused apply is an apply."""
    key = answer(name, index)
    record = corpora[name][index]["run"]
    assert record["mode"] == key["mode"]
    assert record["exit_code"] == key["exit_code"]
    assert record["git_dirty"] is key["git_dirty"]
    assert (record["git_sha"] is not None) is key["is_repository"]


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_the_counts_are_the_ones_the_rules_left_behind(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """A fix reports `auto`, never `eligible`, and may end with more rows than the scan found."""
    key = answer(name, index)["counts"]
    counts = corpora[name][index]["run"]["counts"]
    assert {field: counts[field] for field in key} == key
    assert counts["eligible"] == 0, "a run that applied the rules reports no `eligible` row"


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_the_plan_says_what_the_run_would_write(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """Read off the written `plan.json`, not the in-memory plan."""
    key = answer(name, index)
    plan = corpora[name][index]["plan"]
    assert [
        {"path": row["path"], "hunks": row["hunks"], "rules": row["rules"]} for row in plan["files"]
    ] == key["plan_files"]
    assert [
        {
            "path": row["path"],
            "line": row["line"],
            "status": row["status"],
            **({"rule": row["rule_id"]} if row["status"] == "auto" else {}),
            **({"reason": row["reason"]} if row["reason"] else {}),
            **({"caused_by": row["caused_by"]} if row["caused_by"] else {}),
        }
        for row in plan["edits"]
    ] == key["plan_edits"]
    for absent in ("run_id", "timings", "counts"):
        assert absent not in plan, f"plan.json carries no {absent}"


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_what_reached_the_disk_is_what_the_key_names(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """Without `refused[]`, `dirty/` would look exactly like a run with nothing to do."""
    key = answer(name, index)
    record = corpora[name][index]["run"]
    assert [row["path"] for row in record["file_edits"]] == key["file_edits"]
    assert record["idempotent"] == key["idempotent"]
    assert [{"code": row["code"], "path": row["path"]} for row in record["refused"]] == key[
        "refused"
    ]
    for row in record["refused"]:
        assert row["detail"], "a refusal says something a person can act on"


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_the_withheld_rows_are_the_ones_the_run_refused(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """The findings half of a refusal; `refused[]` is the files half."""
    key = answer(name, index)
    record = corpora[name][index]["run"]
    assert [
        {"path": row["path"], "line": row["line"], "bail": row["bail"]}
        for row in record["withheld"]
    ] == key["withheld"]


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_the_snapshots_are_content_addressed_and_indexed(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """A snapshot no row names is unreachable; a row whose snapshot is missing breaks a revert."""
    key = answer(name, index)["snapshots"]
    here = folder(corpora, name, index)
    record = corpora[name][index]["run"]
    for half, expected in (("before", key["before"]), ("after", key["after"])):
        directory = here / "snapshots" / half
        found = sorted(directory.iterdir()) if directory.exists() else []
        assert len(found) == expected, [path.name for path in found]
        for path in found:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == path.name
        assert {path.name for path in found} == {
            row[f"{half}_sha256"] for row in record["file_edits"]
        }
    for row in record["file_edits"]:
        before = (here / "snapshots" / "before" / row["before_sha256"]).read_bytes()
        assert (
            hashlib.sha256((here.parents[2] / row["path"]).read_bytes()).hexdigest()
            == (row["after_sha256"])
        ), "the file on the disk is the one `file_edits` says was written"
        assert hashlib.sha256(before).hexdigest() == row["before_sha256"]


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_the_verification_is_recorded_and_its_output_has_one_home(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """The record points at the output file and never carries the output."""
    key = answer(name, index)
    here = folder(corpora, name, index)
    verify = corpora[name][index]["run"]["verify"]
    assert verify["status"] == key["verify"]["status"]
    assert verify["reason"] == key["verify"]["reason"]
    assert len(verify["commands"]) == key["verify"]["commands"]
    baseline = verify["baseline"]
    assert (baseline["status"] if baseline else None) == key["verify"]["baseline"]
    found = sorted(relative(here, path) for path in here.rglob("verify/**/*") if path.is_file())
    assert found == key["verify_files"]
    for row in verify["commands"]:
        assert "output" not in row, "the output is a file and never a field"
        if row["log"] is not None:
            assert (here / row["log"]).read_text(encoding="utf-8") == OUTPUT
    if found:
        beside = json.loads((here / "verify" / "verify.json").read_text(encoding="utf-8"))
        assert beside == verify, "one verification, written twice, and they are the same one"
    document = corpora[name][index]["report"]
    assert ("### Baseline" in document) is (key["verify"]["baseline"] is not None)


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_the_patch_carries_the_change_and_git_takes_it_back(
    name: str, index: int, tmp_path: Path, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """Counting hunks proves only the grouping; applying the patch proves the patch."""
    key = answer(name, index)
    patch = corpora[name][index]["patch"]
    changes = corpora[name][index]["changes"]
    assert patch.count(b"\n@@ ") == key["patch_hunks"]
    assert [
        line.removeprefix(b"--- a/").decode("utf-8")
        for line in patch.splitlines()
        if line.startswith(b"--- ")
    ] == key["patch_paths"]
    if not patch:
        assert not changes
        return
    work = tmp_path / "applied"
    for change in changes:
        target = work / change.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(change.before)
    written = work / "patch.diff"
    written.write_bytes(patch)
    subprocess.run(
        ["git", "apply", "--check", "--verbose", str(written)],
        cwd=work,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "apply", str(written)], cwd=work, check=True, capture_output=True)
    assert {change.path: (work / change.path).read_bytes() for change in changes} == {
        change.path: change.after for change in changes
    }


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_the_folder_holds_the_artefacts_the_mode_writes(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """`latest` names a case's last run: the later run owns the pointer (`again/` shows it)."""
    key = answer(name, index)
    here = folder(corpora, name, index)
    assert sorted(path.name for path in here.iterdir() if path.is_file()) == sorted(
        KEY["artefacts"][key["mode"]]
    )
    pointer = here.parents[1] / "latest"
    last = folder(corpora, name, len(CASES[name]["runs"]) - 1)
    assert pointer.read_text(encoding="utf-8") == f"{last.name}\n"
    assert not pointer.is_symlink()


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_the_report_shows_a_reader_the_sections_the_run_has_answers_for(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """`Withheld` and `Not written` come and go; `atomic/` has the first, `dirty/` the second."""
    key = answer(name, index)
    document = corpora[name][index]["report"]
    counts = corpora[name][index]["run"]["counts"]
    assert [
        line.removeprefix("## ") for line in document.splitlines() if line.startswith("## ")
    ] == key["report_sections"]
    assert document.startswith("# obelize fix\n")
    assert f"`{key['mode']}`" in document
    if counts["auto"]:
        assert f"{counts['auto']} auto" in document, "the headline reports section 3's split"


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_an_apply_says_of_each_planned_file_whether_it_landed(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """A dry run carries no `Written` column; in `dirty/` every row says `no`."""
    key = answer(name, index)
    section = _section(corpora[name][index]["report"], "Changes")
    if key["mode"] != "apply" or not key["plan_files"]:
        assert "| Written |" not in section
        return
    assert "| Written |" in section
    for row in key["plan_files"]:
        line = next(one for one in section.splitlines() if one.startswith(f"| `{row['path']}` |"))
        landed = "yes" if row["path"] in key["file_edits"] else "no"
        assert line.rstrip().endswith(f"| {landed} |"), line


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_the_findings_table_is_the_one_the_run_left_and_not_the_one_it_started_with(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """A run can end with more or re-graded rows than the scan found; `atomic/` is that case."""
    document = corpora[name][index]["report"]
    record = corpora[name][index]["run"]
    rows = [line for line in _section(document, "Findings").splitlines() if _ROW.match(line)]
    assert len(rows) == record["counts"]["findings"]


@pytest.mark.parametrize(("name", "index"), RUNS)
def test_the_report_names_every_file_the_findings_do(
    name: str, index: int, corpora: dict[str, list[dict[str, Any]]]
) -> None:
    """A refused file produces no `Edit`, so a report built from edits alone would omit it."""
    document = corpora[name][index]["report"]
    record = corpora[name][index]["run"]
    for path in {row["path"] for row in record["withheld"]}:
        assert f"`{path}`" in document, f"{path} is withheld and the report does not name it"
