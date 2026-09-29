"""`rename_import` on the bundled pack against its answer key, eleven cases, via the real path.

Not under `tests/fixtures/scan/`: `alias_collision` and `type_symbol_unmapped` are the rewrite's,
which `ScanSpec` cannot see (`COVERAGE.md` gap 8). `complete` means this rule claims every eligible
finding, the only case where `.after.py` is what `obelize fix --apply` writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import libcst as cst
import pytest
import yaml

from obelize.impact import planner
from obelize.models import Config, Edit
from obelize.packs import loader
from obelize.scan import analysis, parse, runner
from obelize.transforms import base, registry

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "transforms" / "rename_import"
BUNDLED = loader.load("gemini/google-generativeai-to-google-genai")
SPEC = loader.to_scan_spec(BUNDLED)
KEY: dict[str, Any] = yaml.safe_load((ROOT / "answers.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["file"]: case for case in KEY["cases"]}


def rule() -> Any:
    """A fresh rule, one per pack change."""
    return next(item for item in registry.rules(BUNDLED.pack) if item.kind == "rename_import")


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Copied out: the answer keys sit beside their inputs and would be scanned as sources."""
    work = tmp_path_factory.mktemp("rename_import")
    for path in sorted(ROOT.glob("*.before.py")):
        (work / path.name).write_bytes(path.read_bytes())
    scan = runner.scan(work, Config(), SPEC, jobs=1)
    return {"root": work, "scan": scan}


def outcome(corpus: dict[str, Any], name: str) -> tuple[bytes, tuple[Edit, ...], list[int]]:
    """One case's output bytes, edits, and the eligible lines the rule left."""
    result = next(item for item in corpus["scan"].results if item.path == f"{name}.before.py")
    data = (corpus["root"] / result.path).read_bytes()
    active = rule()
    context = base.RuleContext.build(
        result.plan, cst.parse_module(data), SPEC, [active], BUNDLED.pack.layout
    )
    edits = active.apply(context)
    unclaimed = sorted(
        finding.line
        for finding in result.plan.findings
        if finding.scan_status == "eligible" and not active.claims(finding)
    )
    return base.finish(context).bytes, edits, unclaimed


def test_the_key_grades_every_fixture_and_every_fixture_has_a_row() -> None:
    on_disk = {path.name.removesuffix(".before.py") for path in ROOT.glob("*.before.py")}
    assert on_disk == set(CASES), sorted(on_disk ^ set(CASES))
    keys = {path.name.removesuffix(".after.py") for path in ROOT.glob("*.after.py")}
    assert keys == {name for name, case in CASES.items() if case["after"] == "present"}


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_rule_produces_the_answer_key(name: str, corpus: dict[str, Any]) -> None:
    case = CASES[name]
    produced, _edits, _unclaimed = outcome(corpus, name)
    source = (ROOT / f"{name}.before.py").read_bytes()
    expected = (ROOT / f"{name}.after.py").read_bytes() if case["after"] == "present" else source
    assert produced.decode("utf-8") == expected.decode("utf-8")


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_rule_reports_the_edits_the_key_names(name: str, corpus: dict[str, Any]) -> None:
    _produced, edits, unclaimed = outcome(corpus, name)
    expected = [(row["line"], row["status"], row.get("reason")) for row in CASES[name]["edits"]]
    assert [(row.line, row.status, row.reason) for row in edits] == expected
    assert {row.rule_id for row in edits} == {KEY["rule"]}
    assert unclaimed == CASES[name]["unclaimed"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_complete_means_the_file_a_run_would_write(name: str, corpus: dict[str, Any]) -> None:
    _produced, edits, unclaimed = outcome(corpus, name)
    complete = not unclaimed and all(row.status == "auto" for row in edits)
    assert complete is CASES[name]["complete"]
    if complete:
        assert CASES[name]["after"] == "present", "a file a run migrates owes a key"


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_output_parses_and_compiles(name: str, corpus: dict[str, Any]) -> None:
    produced, _edits, _unclaimed = outcome(corpus, name)
    assert cst.parse_module(produced).bytes == produced
    compile(produced, f"{name}.after.py", "exec")


@pytest.mark.parametrize("name", sorted(CASES))
def test_applying_twice_equals_applying_once(name: str, corpus: dict[str, Any]) -> None:
    """The scan re-runs on the output: idempotence is the whole path's claim, not one rule's."""
    produced, _edits, _unclaimed = outcome(corpus, name)
    read = parse.gates(f"{name}.py", produced)
    if read.module is None:  # pragma: no cover - every case parses, asserted above
        pytest.fail("the produced bytes did not parse")
    plan = planner.plan(analysis.analyse(read, SPEC), SPEC)
    active = rule()
    context = base.RuleContext.build(
        plan, cst.parse_module(produced), SPEC, [active], BUNDLED.pack.layout
    )
    assert [row for row in active.apply(context) if row.status == "auto"] == []
    assert base.finish(context).bytes == produced
