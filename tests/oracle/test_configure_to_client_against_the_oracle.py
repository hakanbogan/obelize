"""`configure_to_client` against its answer key, with both rules run in pack order.

The rule emits `<alias>.Client(...)` with the alias `rename_import` bound. `complete` means every
eligible finding is claimed, so the `.after.py` is exactly what `obelize fix --apply` writes.
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

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "transforms" / "configure_to_client"
BUNDLED = loader.load("gemini/google-generativeai-to-google-genai")
SPEC = loader.to_scan_spec(BUNDLED)
KEY: dict[str, Any] = yaml.safe_load((ROOT / "answers.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["file"]: case for case in KEY["cases"]}

# Legacy `configure` keywords with no new-client equivalent, from its signature and not the
# pack, so a pack edit cannot quietly drop one from this test.
REFUSED = ("transport", "client_options", "client_info", "default_metadata")


def rules() -> list[Any]:
    """Fresh rules, because a rule is constructed once per pack change."""
    return list(registry.rules(BUNDLED.pack))


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Copied out: a scan of the fixture directory would read the `.after.py` keys as sources."""
    work = tmp_path_factory.mktemp("configure_to_client")
    for path in sorted(ROOT.glob("*.before.py")):
        (work / path.name).write_bytes(path.read_bytes())
    return {"root": work, "scan": runner.scan(work, Config(), SPEC, jobs=1)}


def run(plan: Any, data: bytes) -> tuple[bytes, list[Edit], list[int]]:
    """Both rules over one file: its bytes, its edits, and what nothing claimed."""
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
def test_an_applied_edit_names_the_rule_the_key_gives_it_to(
    name: str, corpus: dict[str, Any]
) -> None:
    """Refused rows too: `Edit` requires `rule_id` only when applied, and `run.json` cites by it."""
    _produced, edits, _unclaimed = outcome(corpus, name)
    assert [row.rule_id for row in edits] == [row["rule"] for row in CASES[name]["edits"]]
    assert set(KEY["rules"]) == {change.id for change in BUNDLED.pack.changes} & {
        row["rule"] for case in CASES.values() for row in case["edits"]
    }


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
def test_no_line_of_a_complete_key_is_wider_than_the_pack_allows(
    name: str, corpus: dict[str, Any]
) -> None:
    """Only complete keys: a file no run writes may keep the author's own too-wide lines."""
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
    """The scan is re-run over the output, not reused: idempotence covers the whole path."""
    produced, _edits, _unclaimed = outcome(corpus, name)
    read = parse.gates(f"{name}.py", produced)
    if read.module is None:  # pragma: no cover - every case parses, asserted above
        pytest.fail("the produced bytes did not parse")
    again, edits, _unclaimed = run(planner.plan(analysis.analyse(read, SPEC), SPEC), produced)
    assert [row for row in edits if row.status == "auto"] == []
    assert again == produced


@pytest.mark.parametrize("keyword", REFUSED)
def test_every_keyword_the_new_client_has_no_equivalent_for_bails(
    keyword: str, tmp_path: Path
) -> None:
    """All four, not only the one the corpus has a fixture for."""
    source = (
        f'import google.generativeai as genai\n\ngenai.configure(api_key="k", {keyword}=object())\n'
    )
    (tmp_path / "probe.py").write_text(source, encoding="utf-8", newline="\n")
    scan = runner.scan(tmp_path, Config(), SPEC, jobs=1)
    produced, edits, _unclaimed = run(scan.results[0].plan, source.encode("utf-8"))
    assert [(row.status, row.reason) for row in edits] == [
        ("auto", None),
        ("needs_review", "configure_kwargs_unsupported"),
    ]
    assert produced.decode("utf-8") == source.replace(
        "import google.generativeai as genai", "from google import genai"
    )


def test_the_pack_allows_exactly_the_two_keywords_that_carry() -> None:
    change = next(item for item in BUNDLED.pack.changes if item.kind == "configure_to_client")
    assert change.params.allowed_kwargs == ("api_key", "credentials")
    assert not set(REFUSED) & set(change.params.allowed_kwargs)


# The client line each hand-written Phase 0 scan key states, and the file that holds it.
CLIENT_LINES = {
    "basic": (
        "app.py",
        'client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  # keep this comment',
    ),
    "chat_async_self": (
        "assistant.py",
        "        self.client = genai.Client(api_key=api_key)",
    ),
    "gemini-legacy-app": (
        "summarizer/config.py",
        "client = genai.Client(api_key=API_KEY)",
    ),
}


@pytest.mark.parametrize("case", sorted(CLIENT_LINES), ids=sorted(CLIENT_LINES))
def test_the_rules_produce_the_client_line_the_phase_zero_keys_state(case: str) -> None:
    """Only the client line, as other rules own the rest: module-level twice, `self.` once."""
    path, expected = CLIENT_LINES[case]
    loaded = harness.load(case)
    result = next(item for item in loaded.scan.results if item.path == path)
    produced, _edits, _unclaimed = run(result.plan, (loaded.root / path).read_bytes())
    assert expected in produced.decode("utf-8").splitlines()


def test_the_example_applications_client_module_is_one_the_rules_can_write() -> None:
    """The rules produce both graded edits; a run writing them is the driver's call
    (ADR-031 D11).
    """
    loaded = harness.load("gemini-legacy-app")
    result = next(item for item in loaded.scan.results if item.path == "summarizer/config.py")
    _produced, edits, unclaimed = run(
        result.plan, (loaded.root / "summarizer" / "config.py").read_bytes()
    )
    assert unclaimed == []
    assert [(row.line, row.status, row.rule_id, row.warnings) for row in edits] == [
        (9, "auto", "rename-import", ()),
        (22, "auto", "configure-to-client", ("client_constructed_eagerly",)),
    ]
    row = next(
        item
        for item in loaded.key["findings"]
        if item["file"] == "summarizer/config.py" and item["line"] == 22
    )
    assert row["warnings"] == ["client_constructed_eagerly"], "the key's warning, not ours"
