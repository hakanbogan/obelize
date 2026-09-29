"""`generative_model_calls` against its answer key, with all three rules run in pack order.

The rule calls the client `configure_to_client` placed and reaches the configuration class through
the name `rename_import` bound. The scan fixtures' hand-written Phase 0 keys are graded last.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import harness
import libcst as cst
import pytest
import yaml

from obelize.impact import planner
from obelize.models import Config, Edit
from obelize.packs import loader
from obelize.scan import analysis, parse, runner
from obelize.transforms import base, registry
from obelize.transforms.kinds.generative_model_calls import BAILS

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "transforms" / "generative_model_calls"
BUNDLED = loader.load("gemini/google-generativeai-to-google-genai")
SPEC = loader.to_scan_spec(BUNDLED)
KEY: dict[str, Any] = yaml.safe_load((ROOT / "answers.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["file"]: case for case in KEY["cases"]}

# Graded here but raised by `configure_to_client`; this rule repeats it (one defect, one name).
BORROWED = frozenset({"configure_kwargs_unsupported"})


def rules() -> list[Any]:
    """Fresh rules, because a rule is constructed once per pack change."""
    return list(registry.rules(BUNDLED.pack))


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Copied out: a scan of the fixture directory would read the `.after.py` keys as sources."""
    work = tmp_path_factory.mktemp("generative_model_calls")
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
def test_complete_means_the_file_a_run_would_write(name: str, corpus: dict[str, Any]) -> None:
    """`escaping_model` has nothing eligible; without `bool(edits)` it would count as complete."""
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
    """Both ways: a code with no fixture fails, and so does a graded code the rule cannot raise."""
    graded = {
        row["reason"]
        for case in CASES.values()
        for row in case["edits"]
        if row["rule"] == "generative-model-calls" and row.get("reason")
    }
    assert graded - BORROWED == BAILS
    assert graded & BORROWED == BORROWED


def test_every_rewritten_method_and_every_warning_has_a_case() -> None:
    """`send_message_async` is deliberately unrewritten: it needs `client.aio.chats`, not the
    `client.chats` a `start_chat` becomes, so a file mixing both cannot be written call by call.
    """
    change = next(item for item in BUNDLED.pack.changes if item.kind == "generative_model_calls")
    declared = {
        f"{receiver}.{name}" for receiver, names in change.params.methods.items() for name in names
    }
    assert set(change.params.rewrites) == declared - {
        "google.generativeai.ChatSession.send_message_async"
    }
    warnings = {
        name
        for case in CASES.values()
        for row in case["edits"]
        if row["rule"] == "generative-model-calls"
        for name in row.get("warnings", ())
    }
    assert warnings == {
        "async_stream_await_preserved",
        "count_tokens_config_dropped",
        "history_parts_rewritten",
        "model_name_looks_prefixed",
        "positional_args_mapped_by_index",
    }


def test_the_rules_produce_the_phase_zero_answer_key_for_the_demo() -> None:
    """The hand-written Phase 0 demo key a run must reproduce; never adjust it to fit."""
    loaded = harness.load("basic")
    result = next(item for item in loaded.scan.results if item.path == "app.py")
    produced, edits, unclaimed = run(result.plan, (loaded.root / "app.py").read_bytes())
    assert unclaimed == []
    assert produced == (loaded.root / "app.after.py").read_bytes()
    assert [(row.line, row.status, row.rule_id, row.warnings) for row in edits] == [
        (5, "auto", "rename-import", ()),
        (7, "auto", "configure-to-client", ("client_constructed_eagerly",)),
        (9, "auto", "generative-model-calls", ()),
        (9, "auto", "generative-model-calls", ()),
        (14, "auto", "generative-model-calls", ()),
        (21, "auto", "generative-model-calls", ("count_tokens_config_dropped",)),
    ]


def test_the_warnings_the_demo_key_names_are_the_warnings_the_rules_emit() -> None:
    loaded = harness.load("basic")
    result = next(item for item in loaded.scan.results if item.path == "app.py")
    _produced, edits, _unclaimed = run(result.plan, (loaded.root / "app.py").read_bytes())
    graded = {
        (row["line"], tuple(row.get("warnings", ())))
        for row in loaded.key["findings"]
        if row["file"] == "app.py" and row.get("warnings")
    }
    assert graded == {(7, ("client_constructed_eagerly",)), (21, ("count_tokens_config_dropped",))}
    assert {(row.line, row.warnings) for row in edits if row.warnings} == graded


@pytest.mark.parametrize("name", ["crlf", "latin1_cookie", "no_trailing_newline", "utf8_bom"])
def test_the_encoding_keys_are_produced_with_the_bytes_they_were_written_in(name: str) -> None:
    """The encoding is what libcst records on the module; no rule or write pass touches it."""
    loaded = harness.load("encoding")
    result = next(item for item in loaded.scan.results if item.path == f"{name}.py")
    produced, _edits, unclaimed = run(result.plan, (loaded.root / f"{name}.py").read_bytes())
    assert unclaimed == []
    assert produced == (loaded.root / f"{name}.after.py").read_bytes()


def test_the_rules_produce_the_other_phase_zero_answer_key() -> None:
    """The harder hand-written Phase 0 key; never adjust it to fit the rules."""
    loaded = harness.load("chat_async_self")
    result = next(item for item in loaded.scan.results if item.path == "assistant.py")
    produced, edits, unclaimed = run(result.plan, (loaded.root / "assistant.py").read_bytes())
    assert unclaimed == []
    assert produced == (loaded.root / "assistant.after.py").read_bytes()
    assert [(row.line, row.status, row.rule_id, row.warnings) for row in edits] == [
        (3, "auto", "rename-import", ()),
        (12, "auto", "configure-to-client", ()),
        (13, "auto", "generative-model-calls", ("positional_args_mapped_by_index",)),
        (24, "auto", "generative-model-calls", ()),
        (28, "auto", "generative-model-calls", ()),
        (32, "auto", "generative-model-calls", ("history_parts_rewritten",)),
        (38, "auto", "generative-model-calls", ()),
        (42, "auto", "generative-model-calls", ()),
        (46, "auto", "generative-model-calls", ("async_stream_await_preserved",)),
    ]


def test_the_warnings_the_chat_key_names_are_the_warnings_the_rules_emit() -> None:
    loaded = harness.load("chat_async_self")
    result = next(item for item in loaded.scan.results if item.path == "assistant.py")
    _produced, edits, _unclaimed = run(result.plan, (loaded.root / "assistant.py").read_bytes())
    graded = {
        (row["line"], tuple(row.get("warnings", ())))
        for row in loaded.key["findings"]
        if row["file"] == "assistant.py" and row.get("warnings")
    }
    assert graded == {
        (13, ("positional_args_mapped_by_index",)),
        (32, ("history_parts_rewritten",)),
        (46, ("async_stream_await_preserved",)),
    }
    assert {(row.line, row.warnings) for row in edits if row.warnings} == graded
