"""`flag_only` against its answer key, eleven cases: bytes never change, so the rows are graded.

Unlike the other corpora it runs without the other rules: nothing here writes, and they would add
rows the key is not about.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import libcst as cst
import pytest
import yaml

from obelize.models import Config, Edit
from obelize.packs import loader
from obelize.packs.schema import FlagOnlyChange
from obelize.scan import runner
from obelize.transforms import base, registry
from obelize.transforms.kinds.flag_only import BAILS, REASONS

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "transforms" / "flag_only"
BUNDLED = loader.load("gemini/google-generativeai-to-google-genai")
SPEC = loader.to_scan_spec(BUNDLED)
KEY: dict[str, Any] = yaml.safe_load((ROOT / "answers.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["file"]: case for case in KEY["cases"]}


def flagging() -> list[Any]:
    return [item for item in registry.rules(BUNDLED.pack) if item.kind == "flag_only"]


def changes() -> list[FlagOnlyChange]:
    return [item for item in BUNDLED.pack.changes if isinstance(item, FlagOnlyChange)]


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    work = tmp_path_factory.mktemp("flag_only")
    for path in sorted(ROOT.glob("*.before.py")):
        (work / path.name).write_bytes(path.read_bytes())
    return {"root": work, "scan": runner.scan(work, Config(), SPEC, jobs=1)}


def outcome(corpus: dict[str, Any], name: str) -> tuple[bytes, list[tuple[str, Edit]]]:
    """One case's bytes and `(rule_id, edit)` pairs from every `flag_only` rule."""
    result = next(item for item in corpus["scan"].results if item.path == f"{name}.before.py")
    data = (corpus["root"] / result.path).read_bytes()
    rules = flagging()
    context = base.RuleContext.build(
        result.plan, cst.parse_module(data), SPEC, rules, BUNDLED.pack.layout
    )
    edits = [(row.rule_id or "", row) for rule in rules for row in rule.apply(context)]
    return base.finish(context).bytes, edits


def test_the_key_grades_every_fixture_and_every_fixture_has_a_row() -> None:
    on_disk = {path.name.removesuffix(".before.py") for path in ROOT.glob("*.before.py")}
    assert on_disk == set(CASES), sorted(on_disk ^ set(CASES))
    assert list(ROOT.glob("*.after.py")) == [], "this kind never writes, so it owes no key"


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_file_comes_back_exactly_as_it_went_in(name: str, corpus: dict[str, Any]) -> None:
    produced, _edits = outcome(corpus, name)
    assert produced == (ROOT / f"{name}.before.py").read_bytes()


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_rules_report_the_edits_the_key_names(name: str, corpus: dict[str, Any]) -> None:
    _produced, edits = outcome(corpus, name)
    expected = [(row["line"], row["status"], row["reason"]) for row in CASES[name]["edits"]]
    assert [(row.line, row.status, row.reason) for _id, row in edits] == expected
    assert {row.path for _id, row in edits} <= {f"{name}.before.py"}


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_edit_names_the_change_that_refused_it(name: str, corpus: dict[str, Any]) -> None:
    case = CASES[name]
    _produced, edits = outcome(corpus, name)
    by_rule: dict[str, list[int]] = {}
    for identifier, row in edits:
        by_rule.setdefault(identifier, []).append(row.line)
    if "rules" in case:
        assert by_rule == case["rules"]
        return
    lines = [row["line"] for row in case["edits"]]
    assert by_rule == ({case["rule"]: lines} if lines else {})


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_flagged_row_is_claimed_by_exactly_one_change(
    name: str, corpus: dict[str, Any]
) -> None:
    """A surface with no owner has no message; one with two reports twice."""
    result = next(item for item in corpus["scan"].results if item.path == f"{name}.before.py")
    rules = flagging()
    for finding in result.plan.findings:
        owners = [rule for rule in rules if rule.claims(finding)]
        expected = 1 if finding.bail in BAILS else 0
        assert len(owners) == expected, (finding.line, finding.symbol, finding.bail)


def test_the_corpus_reads_every_name_the_pack_declares(corpus: dict[str, Any]) -> None:
    """Symbols match by prefix; `sys_modules_stub` is `dynamic_access`, so its case grades it."""
    rows = list(corpus["scan"].findings)
    for change in changes():
        for symbol in change.params.symbols:
            assert any(
                row.bail == "flag_only_surface"
                and (row.symbol == symbol or (row.symbol or "").startswith(symbol + "."))
                for row in rows
            ), symbol
        for attribute in change.params.attributes:
            assert any(
                row.bail == "attribute_removed" and row.symbol == attribute for row in rows
            ), attribute
        for pattern in change.params.patterns:
            assert any(
                row.bail == "flag_only_surface" and row.confidence_reason == REASONS[pattern]
                for row in rows
            ), pattern


def test_the_corpus_grades_every_bail_this_rule_reports() -> None:
    """`scan/analysis.py` raises these; one no case grades is a refusal the corpus never saw."""
    graded = {row["reason"] for case in CASES.values() for row in case["edits"]}
    assert graded == BAILS
