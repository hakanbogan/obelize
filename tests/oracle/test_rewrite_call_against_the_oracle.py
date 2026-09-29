"""`rewrite_call` against its answer key: twenty-four cases, eight rules (one per legacy function).

Every rule runs in pack order, because this kind builds on the names `configure_to_client` and
`rename_import` bind; an edit's `rule_id` says which of the eight changes fired.
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
from obelize.transforms.kinds.rewrite_call import BAILS

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "transforms" / "rewrite_call"
BUNDLED = loader.load("gemini/google-generativeai-to-google-genai")
SPEC = loader.to_scan_spec(BUNDLED)
KEY: dict[str, Any] = yaml.safe_load((ROOT / "answers.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["file"]: case for case in KEY["cases"]}

# The planner's code for a module with no `configure`, raised by this rule (`COVERAGE.md` gap 21).
BORROWED = frozenset({"client_source_unresolved"})

CHANGES = [change for change in BUNDLED.pack.changes if change.kind == "rewrite_call"]


def rules() -> list[Any]:
    """Fresh rules, one per pack change."""
    return list(registry.rules(BUNDLED.pack))


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Copied out: the answer keys sit beside their inputs and would be scanned as sources."""
    work = tmp_path_factory.mktemp("rewrite_call")
    for path in sorted(ROOT.glob("*.before.py")):
        (work / path.name).write_bytes(path.read_bytes())
    return {"root": work, "scan": runner.scan(work, Config(), SPEC, jobs=1)}


def run(plan: Any, data: bytes) -> tuple[bytes, list[Edit], list[int]]:
    """Every rule over one file: its bytes, its edits, and what nothing claimed."""
    active = rules()
    context = base.RuleContext.build(
        plan, cst.parse_module(data), SPEC, active, BUNDLED.pack.layout
    )
    edits = [row for rule in active for row in rule.apply(context)]
    unclaimed = sorted(
        finding.line
        for finding in plan.findings
        if finding.scan_status == "eligible" and not any(rule.claims(finding) for rule in active)
    )
    return base.finish(context).bytes, edits, unclaimed


def outcome(corpus: dict[str, Any], name: str) -> tuple[bytes, list[Edit], list[int]]:
    result = next(item for item in corpus["scan"].results if item.path == f"{name}.before.py")
    return run(result.plan, (corpus["root"] / result.path).read_bytes())


def test_the_key_grades_every_fixture_and_every_fixture_has_a_row() -> None:
    on_disk = {path.name.removesuffix(".before.py") for path in ROOT.glob("*.before.py")}
    assert on_disk == set(CASES), sorted(on_disk ^ set(CASES))
    keys = {path.name.removesuffix(".after.py") for path in ROOT.glob("*.after.py")}
    assert keys == {name for name, case in CASES.items() if case["after"] == "present"}


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_rules_produce_the_answer_key(name: str, corpus: dict[str, Any]) -> None:
    """A refusal still has a key, since two other rules wrote; ADR-010 F-1 keeps it off disk."""
    case = CASES[name]
    produced, _edits, _unclaimed = outcome(corpus, name)
    source = (ROOT / f"{name}.before.py").read_bytes()
    expected = (ROOT / f"{name}.after.py").read_bytes() if case["after"] == "present" else source
    assert produced.decode("utf-8") == expected.decode("utf-8")


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_rules_report_the_edits_the_key_names(name: str, corpus: dict[str, Any]) -> None:
    _produced, edits, unclaimed = outcome(corpus, name)
    expected = [
        (row["line"], row["rule"], row["status"], row.get("reason"), tuple(row.get("warnings", ())))
        for row in CASES[name]["edits"]
    ]
    assert [
        (row.line, row.rule_id, row.status, row.reason, row.warnings) for row in edits
    ] == expected
    assert unclaimed == CASES[name]["unclaimed"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_an_applied_edit_names_the_rule_the_key_gives_it_to(
    name: str, corpus: dict[str, Any]
) -> None:
    _produced, edits, _unclaimed = outcome(corpus, name)
    assert [row.rule_id for row in edits] == [row["rule"] for row in CASES[name]["edits"]]
    assert set(KEY["rules"]) == {change.id for change in BUNDLED.pack.changes} & {
        row["rule"] for case in CASES.values() for row in case["edits"]
    }


@pytest.mark.parametrize("name", sorted(CASES))
def test_complete_means_the_file_a_run_would_write(name: str, corpus: dict[str, Any]) -> None:
    _produced, edits, unclaimed = outcome(corpus, name)
    complete = bool(edits) and not unclaimed and all(row.status == "auto" for row in edits)
    assert complete is CASES[name]["complete"]
    if complete:
        assert CASES[name]["after"] == "present", "a file a run migrates owes a key"


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_output_parses_and_compiles(name: str, corpus: dict[str, Any]) -> None:
    produced, _edits, _unclaimed = outcome(corpus, name)
    assert cst.parse_module(produced).bytes == produced
    compile(produced, f"{name}.after.py", "exec")


@pytest.mark.parametrize("name", sorted(CASES))
def test_no_line_of_a_complete_key_is_wider_than_the_pack_allows(
    name: str, corpus: dict[str, Any]
) -> None:
    if not CASES[name]["complete"]:
        pytest.skip("a file no run writes is not this rule's output to measure")
    produced, _edits, _unclaimed = outcome(corpus, name)
    wide = [
        line
        for line in produced.decode("utf-8").splitlines()
        if len(line) > BUNDLED.pack.layout.line_length
    ]
    assert wide == []


@pytest.mark.parametrize("name", sorted(CASES))
def test_applying_twice_equals_applying_once(name: str, corpus: dict[str, Any]) -> None:
    produced, _edits, _unclaimed = outcome(corpus, name)
    read = parse.gates(f"{name}.py", produced)
    if read.module is None:  # pragma: no cover - every case parses, asserted above
        pytest.fail("the produced bytes did not parse")
    again, edits, _unclaimed = run(planner.plan(analysis.analyse(read, SPEC), SPEC), produced)
    assert [row for row in edits if row.status == "auto"] == []
    assert again == produced


def test_the_corpus_grades_every_bail_this_rule_raises() -> None:
    ids = {change.id for change in CHANGES}
    graded = {
        row["reason"]
        for case in CASES.values()
        for row in case["edits"]
        if row["rule"] in ids and row.get("reason")
    }
    assert graded - BORROWED == BAILS
    assert graded & BORROWED == BORROWED


def test_every_change_of_this_kind_has_a_case() -> None:
    """The development corpus never used four of these surfaces; fixtures are their only run."""
    fired = {row["rule"] for case in CASES.values() for row in case["edits"]}
    assert {change.id for change in CHANGES} <= fired
    assert len(CHANGES) == 8


def test_every_parameter_the_pack_declares_is_read_by_some_case() -> None:
    """Only an output byte proves a parameter is read; a refusal case covers `dispatch_prefixes`."""
    keys = "".join(path.read_text(encoding="utf-8") for path in ROOT.glob("*.after.py"))
    for change in CHANGES:
        params = change.params
        for legacy, new in sorted(params.arg_map.items()):
            assert f"{new}=" in keys, f"{change.id} renames {legacy} and no key shows {new}="
        if params.config_class:
            assert f"{params.config_class.rpartition('.')[2]}(" in keys, change.id
        for field in params.config_kwargs:
            assert f"{field}=" in keys, f"{change.id} carries {field} and no key shows it"
