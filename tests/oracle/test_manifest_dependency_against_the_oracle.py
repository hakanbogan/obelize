"""`manifest_dependency` on the bundled pack against its answer key, five small repositories.

A manifest's verdict depends on the Python beside it (ADR-010 F-2), so each case is a directory
scanned whole before the rule runs over each manifest's bytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import harness
import pytest
import yaml

from obelize.models import Config, Edit, ManifestPlan
from obelize.packs import loader
from obelize.scan import manifests, runner
from obelize.transforms import manifest as manifest_transform
from obelize.transforms import registry

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "transforms" / "manifest_dependency"
BUNDLED = loader.load("gemini/google-generativeai-to-google-genai")
SPEC = loader.to_scan_spec(BUNDLED)
KEY: dict[str, Any] = yaml.safe_load((ROOT / "answers.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["case"]: case for case in KEY["cases"]}
SUFFIX = ".after"


def rule() -> Any:
    """A fresh rule, one per pack change."""
    return next(item for item in registry.manifest_rules(BUNDLED.pack))


def copied(source: Path, destination: Path) -> None:
    """Copy a case's inputs: every file but its answer keys."""
    for path in sorted(source.rglob("*")):
        if path.is_dir() or path.name.endswith(SUFFIX):
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def scanned(work: Path) -> runner.Scan:
    return runner.scan(work, Config(), SPEC, jobs=1)


def written(work: Path, plan: ManifestPlan, name: str) -> tuple[bytes, tuple[Edit, ...]]:
    data = (work / name).read_bytes()
    context = manifest_transform.ManifestContext.build(name, data, plan)
    active = rule()
    edits = active.apply(context)
    return manifest_transform.finish(context), edits


@pytest.fixture(scope="module")
def corpora(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    built: dict[str, dict[str, Any]] = {}
    for name in sorted(CASES):
        work = tmp_path_factory.mktemp(name)
        copied(ROOT / name, work)
        built[name] = {"root": work, "scan": scanned(work)}
    return built


def test_the_key_grades_every_case_and_every_case_has_a_row() -> None:
    on_disk = {path.name for path in ROOT.iterdir() if path.is_dir()}
    assert on_disk == set(CASES), sorted(on_disk ^ set(CASES))


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_key_grades_every_manifest_and_every_manifest_has_a_row(name: str) -> None:
    case = ROOT / name
    found = {
        str(path.relative_to(case).as_posix())
        for path in sorted(case.rglob("*"))
        if path.is_file() and not path.name.endswith(SUFFIX)
        if manifests.is_manifest(str(path.relative_to(case).as_posix()))
    }
    graded = {row["file"] for row in CASES[name]["manifests"]}
    assert found == graded, sorted(found ^ graded)
    keys = {
        str(path.relative_to(case).as_posix()).removesuffix(SUFFIX)
        for path in sorted(case.rglob("*" + SUFFIX))
    }
    assert keys == {row["file"] for row in CASES[name]["manifests"] if row["after"] == "present"}


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_repository_is_in_the_state_the_key_describes(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    """Read off the scan, not trusted: a case's Python decides its verdict."""
    scan = corpora[name]["scan"]
    survey = manifests.survey(result.plan for result in scan.results)
    assert list(survey.migrated) == CASES[name]["migrated"]
    assert list(survey.blocking) == CASES[name]["blocking"]
    assert scan.manifests.blocking == survey.blocking


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_rule_produces_the_answer_key(name: str, corpora: dict[str, dict[str, Any]]) -> None:
    work, scan = corpora[name]["root"], corpora[name]["scan"]
    for row in CASES[name]["manifests"]:
        produced, _edits = written(work, scan.manifests, row["file"])
        source = (ROOT / name / row["file"]).read_bytes()
        expected = (
            (ROOT / name / (row["file"] + SUFFIX)).read_bytes()
            if row["after"] == "present"
            else source
        )
        assert produced.decode("utf-8") == expected.decode("utf-8"), row["file"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_rule_reports_the_edits_the_key_names(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    work, scan = corpora[name]["root"], corpora[name]["scan"]
    for row in CASES[name]["manifests"]:
        _produced, edits = written(work, scan.manifests, row["file"])
        expected = [(item["line"], item["status"], item.get("reason")) for item in row["edits"]]
        assert [(item.line, item.status, item.reason) for item in edits] == expected, row["file"]
        assert {item.rule_id for item in edits} <= {KEY["rule"]}
        assert {item.path for item in edits} <= {row["file"]}


@pytest.mark.parametrize("name", sorted(CASES))
def test_applying_twice_equals_applying_once(
    name: str, corpora: dict[str, dict[str, Any]], tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Re-scanned: a replacement leaves no legacy pin, an insertion leaves the new one declared."""
    work, scan = corpora[name]["root"], corpora[name]["scan"]
    again = tmp_path_factory.mktemp(name + "-again")
    copied(ROOT / name, again)
    for row in CASES[name]["manifests"]:
        produced, _edits = written(work, scan.manifests, row["file"])
        (again / row["file"]).write_bytes(produced)
    second = scanned(again)
    for row in CASES[name]["manifests"]:
        before = (again / row["file"]).read_bytes()
        produced, edits = written(again, second.manifests, row["file"])
        assert produced == before, row["file"]
        assert [item for item in edits if item.status == "auto"] == [], row["file"]


def test_the_basic_case_gets_the_key_its_ground_truth_has_always_named() -> None:
    """The one oracle repository where nothing is withheld, so the removal is not blocked."""
    case = harness.load("basic")
    name = "requirements.txt"
    data = (case.root / name).read_bytes()
    context = manifest_transform.ManifestContext.build(name, data, case.scan.manifests)
    active = rule()
    edits = active.apply(context)
    assert [(row.line, row.status, row.reason) for row in edits] == [(1, "auto", None)]
    produced = manifest_transform.finish(context)
    assert produced.decode("utf-8") == (case.root / "requirements.after.txt").read_text("utf-8")


def test_the_example_application_gets_the_third_edit_its_key_has_always_named() -> None:
    """The scan's plan, not a run's: a run withholds `config.py` (ADR-031 D11) and owes nothing.

    Expected bytes are inline: this is the e2e subject, and a `requirements.after.txt` in it would
    scan as a second declaration of the new distribution (`manifest_code_mismatch`).
    """
    case = harness.load("gemini-legacy-app")
    name = "requirements.txt"
    data = (case.root / name).read_bytes()
    context = manifest_transform.ManifestContext.build(name, data, case.scan.manifests)
    active = rule()
    edits = active.apply(context)
    assert [(row.line, row.status, row.reason) for row in edits] == [
        (3, "auto", None),
        (3, "needs_review", "repo_not_fully_migrated"),
    ]
    assert "summarizer/summarize.py" in case.scan.manifests.blocking
    assert case.scan.manifests.excluded == ("scripts/oneoff_backfill.py",)
    produced = manifest_transform.finish(context).decode("utf-8")
    assert produced == data.decode("utf-8").replace(
        "google-generativeai==0.8.6\n",
        "google-generativeai==0.8.6\ngoogle-genai>=1\n",
    )
