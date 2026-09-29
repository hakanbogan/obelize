"""The codemod driver against its answer key: each case is a repository, run end to end.

The whole path (walk, scan, every `Rule`, the survey, every `ManifestRule`) with the bundled pack.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import libcst as cst
import pytest
import yaml
from unresolved import names_unresolved

from obelize import config as configuration
from obelize.models import Config
from obelize.packs import loader
from obelize.scan import manifests, runner, walker
from obelize.transforms import codemod

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "transforms" / "codemod"
REPOSITORY = Path(__file__).resolve().parents[2]
BASIC = REPOSITORY / "tests" / "fixtures" / "scan" / "basic"
EXAMPLE = REPOSITORY / "examples" / "gemini-legacy-app"
BUNDLED = loader.load("gemini/google-generativeai-to-google-genai")
SPEC = loader.to_scan_spec(BUNDLED)
KEY: dict[str, Any] = yaml.safe_load((ROOT / "answers.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["case"]: case for case in KEY["cases"]}

# Key names: `<file>.after` for a manifest, `<stem>.after.py` for Python so the key stays `.py`.
SUFFIXES = (".after", ".after.py")


def is_key(name: str) -> bool:
    return name.endswith(SUFFIXES)


def answer(case: Path, name: str) -> Path:
    if name.endswith(".py"):
        return case / (name.removesuffix(".py") + ".after.py")
    return case / (name + ".after")


def copied(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_dir() or is_key(path.name) or path.name == "ground_truth.yaml":
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def migrate(work: Path, config: Config | None = None) -> codemod.Run:
    config = config or Config()
    scan = runner.scan(work, config, SPEC, jobs=1)
    selection = walker.walk(work, config)
    wanted = {result.path for result in scan.results} | set(selection.manifests)
    sources = {name: (work / name).read_bytes() for name in sorted(wanted)}
    return codemod.run(scan, sources, BUNDLED.pack, SPEC)


@pytest.fixture(scope="module")
def corpora(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    built: dict[str, dict[str, Any]] = {}
    for name in sorted(CASES):
        work = tmp_path_factory.mktemp(name)
        copied(ROOT / name, work)
        built[name] = {"root": work, "run": migrate(work)}
    return built


def outcome(corpora: dict[str, dict[str, Any]], case: str, name: str) -> codemod.Outcome:
    """One file as the run left it; a file the scan never read comes back unchanged."""
    run: codemod.Run = corpora[case]["run"]
    found = next((row for row in run.outcomes if row.path == name), None)
    if found is None:
        data = (corpora[case]["root"] / name).read_bytes()
        return codemod.Outcome(path=name, before=data, after=data, edits=())
    return found


def test_the_key_grades_every_case_and_every_case_has_a_row() -> None:
    on_disk = {path.name for path in ROOT.iterdir() if path.is_dir()}
    assert on_disk == set(CASES), sorted(on_disk ^ set(CASES))


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_key_grades_every_file_and_every_file_has_a_row(name: str) -> None:
    case = ROOT / name
    found = {
        str(path.relative_to(case).as_posix())
        for path in sorted(case.rglob("*"))
        if path.is_file() and not is_key(path.name)
    }
    graded = {row["file"] for row in CASES[name]["files"]}
    assert found == graded, sorted(found ^ graded)
    keys = {
        str(path.relative_to(case).as_posix()).removesuffix(".after").replace(".after.py", ".py")
        for path in sorted(case.rglob("*"))
        if path.is_file() and is_key(path.name)
    }
    assert keys == {row["file"] for row in CASES[name]["files"] if row["after"] == "present"}


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_repository_is_in_the_state_the_key_describes(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    """Asked of the run's plans: `blocked/` and `clear/` differ in nothing a scan can see."""
    run = corpora[name]["run"]
    survey = manifests.survey(run.plans)
    assert list(survey.migrated) == CASES[name]["migrated"]
    assert list(run.manifest_plan.blocking) == CASES[name]["blocking"]
    assert list(run.manifest_plan.transitive) == CASES[name].get("transitive", [])


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_file_comes_out_as_the_key_says(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    for row in CASES[name]["files"]:
        produced = outcome(corpora, name, row["file"])
        expected = (
            answer(ROOT / name, row["file"]).read_bytes()
            if row["after"] == "present"
            else produced.before
        )
        assert produced.after == expected, row["file"]
        assert produced.written is row["written"], row["file"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_file_reports_the_rows_the_key_names(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    for row in CASES[name]["files"]:
        produced = outcome(corpora, name, row["file"])
        expected = [
            (
                edit["line"],
                edit["rule"],
                edit["status"],
                edit.get("reason"),
                tuple(edit["caused_by"]) if edit.get("caused_by") else None,
            )
            for edit in row["edits"]
        ]
        assert [
            (edit.line, edit.rule_id, edit.status, edit.reason, edit.caused_by)
            for edit in produced.edits
        ] == expected, row["file"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_what_a_run_writes_is_what_the_key_marks_written(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    run = corpora[name]["run"]
    assert [row.path for row in run.written] == [
        row["file"] for row in CASES[name]["files"] if row["written"]
    ]


@pytest.mark.parametrize("name", sorted(CASES))
def test_everything_written_parses_and_compiles(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    for row in corpora[name]["run"].written:
        if not row.path.endswith(".py"):
            continue
        assert cst.parse_module(row.after).bytes == row.after
        compile(row.after, row.path, "exec")


@pytest.mark.parametrize("name", sorted(CASES))
def test_everything_written_binds_every_name_it_reads(
    name: str, corpora: dict[str, dict[str, Any]], tmp_path: Path
) -> None:
    """ruff re-checks what the driver's own name gate passed (ADR-031 D10)."""
    for row in corpora[name]["run"].written:
        target = tmp_path / row.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(row.after)
    assert names_unresolved(tmp_path) == ""


@pytest.mark.parametrize("name", sorted(CASES))
def test_applying_twice_equals_applying_once(
    name: str, corpora: dict[str, dict[str, Any]], tmp_path: Path
) -> None:
    work = tmp_path / name
    copied(corpora[name]["root"], work)
    for row in corpora[name]["run"].written:
        (work / row.path).write_bytes(row.after)
    again = migrate(work)
    assert [row for row in again.edits if row.status == "auto"] == []
    assert again.written == ()


def test_the_corpus_grades_the_code_the_driver_raises_and_says_which_it_cannot() -> None:
    """No real rule can trip the output gates; `tests/unit/test_codemod.py` uses a broken one."""
    graded = {
        edit.get("reason")
        for case in CASES.values()
        for row in case["files"]
        for edit in row["edits"]
    }
    assert codemod.UNCLAIMED in graded
    assert codemod.GATE not in graded
    assert codemod.BAILS - graded == {codemod.GATE, codemod.UNRESOLVED}


def test_the_basic_fixture_is_migrated_whole(tmp_path: Path) -> None:
    """Both hand-written Phase 0 demo keys, from one call; never adjust them to fit."""
    copied(BASIC, tmp_path)
    run = migrate(tmp_path)
    assert [row.path for row in run.written] == ["app.py", "requirements.txt"]
    assert run.files[0].after == (BASIC / "app.after.py").read_bytes()
    assert run.manifests[0].after == (BASIC / "requirements.after.txt").read_bytes()
    assert all(row.status == "auto" for row in run.edits), run.edits


def test_the_example_application_is_withheld_whole(tmp_path: Path) -> None:
    """Two modules stay on the legacy SDK and run on `summarizer/config.py`'s `configure`.

    The example's own configuration is loaded so its excluded script stays excluded.
    """
    copied(EXAMPLE, tmp_path)
    run = migrate(tmp_path, configuration.load(tmp_path).config)
    assert [row for row in run.edits if row.status == "auto"] == []
    assert run.written == ()
    held = next(row for row in run.files if row.path == "summarizer/config.py")
    assert [(row.line, row.rule_id, row.reason, row.caused_by) for row in held.edits] == [
        (9, "rename-import", "file_not_fully_migrated", ("configure_consumed_elsewhere",)),
        (22, "configure-to-client", "configure_consumed_elsewhere", None),
    ]


def test_the_example_application_keeps_its_manifest(tmp_path: Path) -> None:
    """Nothing migrated, so the pin stays, blocked by the module holding the `configure` too."""
    copied(EXAMPLE, tmp_path)
    run = migrate(tmp_path, configuration.load(tmp_path).config)
    assert {"summarizer/config.py", "summarizer/summarize.py"} <= set(run.manifest_plan.blocking)
    manifest = next(row for row in run.manifests if row.path == "requirements.txt")
    assert manifest.written is False
