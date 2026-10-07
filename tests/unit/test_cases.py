"""`bench/cases.yaml` is recomputed from corpus, draws, scans and pack; the key is hand-written."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from platforms import BENCH

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import candidates  # noqa: E402
import cases  # noqa: E402
from gate1_score import ACTIONABLE_KINDS, rows  # noqa: E402

pytestmark = BENCH

CORPUS = cases.load()
CASES = cases.cases(CORPUS)
CONTROLS = cases.controls(CORPUS)
CHANGES = {surface.change for surface in candidates.surfaces()}

# Call-site kinds plus `dynamic`: the legacy module named as a string (patch target or
# `sys.modules` stub). Excluded from the rate, but two cases reach the SDK only that way.
KINDS: frozenset[str] = ACTIONABLE_KINDS | {"dynamic"}

# `uv python list --only-installed` on this round's machine; a case may name no other interpreter.
INTERPRETERS: frozenset[str] = frozenset(
    {
        "cpython-3.10.21-macos-aarch64-none",
        "cpython-3.11.11-macos-aarch64-none",
        "cpython-3.12.9-macos-aarch64-none",
        "cpython-3.13.5-macos-aarch64-none",
    }
)

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def site(**overrides: Any) -> dict[str, Any]:
    row = {
        "path": "app.py",
        "line": 1,
        "kind": "call",
        "symbol": "google.generativeai.configure",
        "label": "auto",
    }
    row.update(overrides)
    return row


def repo(**overrides: Any) -> dict[str, Any]:
    row = {
        "full_name": "owner/repo",
        "owner": "owner",
        "url": "https://github.com/owner/repo",
        "sha": "a" * 40,
        "license": "MIT",
        "fork": False,
        "archived": False,
        "pushed_at": "2026-09-01T00:00:00Z",
        "stars": 1,
        "size_kb": 10,
        "source": "frame",
        "tests": {},
    }
    row.update(overrides)
    return row


def case(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "owner__repo",
        "provider": "gemini",
        "change": "google-generativeai-to-google-genai",
        "from_version": "0.8.6",
        "to_version": "2.24.0",
        "full_name": "owner/repo",
        "owner": "owner",
        "repo": "https://github.com/owner/repo",
        "sha": "a" * 40,
        "license": "MIT",
        "split": "dev",
        "pattern_key": ["google.generativeai.configure"],
        "python": cases.DEFAULT_PYTHON,
        "install": [],
        "test_cmd": None,
        "tests_require_network": False,
        "ground_truth": {
            "what_it_is": "one line",
            "files_read": ["app.py"],
            "call_sites": [site()],
            "manifests": [],
            "must_not_report": [],
            "tests_cover_change": False,
            "tests_cover_change_why": "no tests",
        },
        "reviewer": "Hakan Bogan",
        "reviewed_at": "2026-09-21",
        "notes": "a note",
    }
    row.update(overrides)
    return row


def control(**overrides: Any) -> dict[str, Any]:
    row = {
        "control": "vertex-preview",
        "shape": "vertexai.preview.generative_models",
        "full_name": "other/repo",
        "owner": "other",
        "repo": "https://github.com/other/repo",
        "sha": "b" * 40,
        "license": "MIT",
        "witness": "api.py:1",
        "query": "q",
        "must_produce": "nothing",
        "reviewer": "Hakan Bogan",
        "reviewed_at": "2026-09-21",
        "notes": "a note",
    }
    row.update(overrides)
    return row


def draws(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "drawn_at": "2026-09-21T00:00:00Z",
        "test_suites": {
            "query": "q",
            "hits": 1,
            "examined": 1,
            "outcome": "drawn",
            "keep": 5,
            "drawn": ["owner/repo"],
            "skipped": [],
        },
        "controls": [
            {
                "control": "vertex-preview",
                "shape": "s",
                "query": "q",
                "hits": 1,
                "examined": 1,
                "outcome": "drawn",
                "drawn": "other/repo",
                "witness": "api.py:1",
                "skipped": [],
            }
        ],
        "drawn": [],
    }
    row.update(overrides)
    return row


def corpus(
    rows_: list[dict[str, Any]],
    controls_: list[dict[str, Any]] | None = None,
    repositories_: dict[str, dict[str, Any]] | None = None,
    findings_: dict[str, list[dict[str, Any]]] | None = None,
    draws_: dict[str, Any] | None = None,
) -> cases.Corpus:
    known = repositories_ or {
        entry["full_name"]: repo(full_name=entry["full_name"], owner=entry["owner"])
        for entry in [*rows_, *(controls_ or [])]
    }
    return cases.Corpus(
        cases={
            "round": 1,
            "reviewer": "Hakan Bogan",
            "reviewed_at": "2026-09-21",
            "from_version": "0.8.6",
            "to_version": "2.24.0",
            "cases": rows_,
            "controls": controls_ or [],
        },
        draws=draws_ or draws(),
        repositories=known,
        findings=findings_ or {},
    )


def test_a_pattern_key_counts_call_sites_and_nothing_else() -> None:
    """A `dynamic` row is the module named as a string, not a symbol the case uses."""
    one = case(
        ground_truth={
            **case()["ground_truth"],
            "call_sites": [
                site(symbol="google.generativeai", kind="import"),
                site(symbol="google.generativeai.GenerativeModel", kind="dynamic"),
            ],
        }
    )
    assert cases.ground_truth_key(one) == ("google.generativeai",)


def test_a_call_site_renders_in_the_form_the_benchmark_document_names() -> None:
    assert cases.rendered(site(path="a/b.py", line=9)) == (
        "a/b.py:9:google.generativeai.configure:auto"
    )
    assert cases.CALL_SITE.match(cases.rendered(site()))
    assert not cases.CALL_SITE.match("a/b.py:9:google.generativeai.configure:perhaps")
    assert not cases.CALL_SITE.match("a/b.py:google.generativeai.configure:auto")


def test_the_label_and_split_vocabularies_are_closed() -> None:
    """`docs/BENCHMARK.md` defines two of each; a third word is a judgement nobody defined."""
    assert cases.LABELS == ("auto", "manual")
    assert cases.SPLITS == ("dev", "holdout")
    assert cases.HOLDOUT_SHARE == 1 / 3
    assert cases.CASE_COUNT == 20


def test_a_case_is_verifiable_exactly_when_it_has_a_test_command() -> None:
    assert not cases.verifiable(case())
    assert cases.verifiable(case(test_cmd="pytest -q"))


def test_a_control_is_never_a_positive_case() -> None:
    assert cases.is_control(repo(source="control:vertex-preview"))
    assert not cases.is_control(repo(source="tests"))


def test_only_a_python_test_file_makes_a_repository_testable() -> None:
    """A CI workflow is not a suite, which is what the stratified split turns on."""
    assert cases.testable(repo(tests={"test_files": "tests/test_a.py"}))
    assert not cases.testable(repo(tests={"ci_workflow": ".github/workflows/ci.yml"}))


def test_a_bare_version_is_not_a_pin_and_a_bare_interpreter_is_not_a_key() -> None:
    """Both short forms resolve to anything."""
    assert cases.EXACT_VERSION.match("0.8.6")
    assert not cases.EXACT_VERSION.match(">=0.8")
    assert not cases.EXACT_VERSION.match("0.8")
    assert cases.INTERPRETER_KEY.match(cases.DEFAULT_PYTHON)
    assert not cases.INTERPRETER_KEY.match("3.12")
    assert not cases.INTERPRETER_KEY.match("cpython-3.12-macos-aarch64-none")


def test_a_control_may_not_produce_a_pin_either() -> None:
    assert "manifest" in cases.CONTROL_KINDS
    assert ACTIONABLE_KINDS < cases.CONTROL_KINDS


def test_the_draw_vocabulary_extends_the_corpus_one_and_does_not_replace_it() -> None:
    assert set(candidates.SKIP_REASONS) < set(cases.DRAW_SKIP_REASONS)
    assert {"no_test_file", "not_a_control", "no_witness"} <= set(cases.DRAW_SKIP_REASONS)


def test_every_repository_with_a_test_file_is_taken_first() -> None:
    rows_ = {
        "a/one": repo(full_name="a/one", owner="a"),
        "b/two": repo(full_name="b/two", owner="b", tests={"test_files": "tests/t.py"}),
    }
    assert cases.chosen(rows_, {})[0] == "b/two"


def test_a_control_is_never_chosen() -> None:
    rows_ = {
        "a/one": repo(full_name="a/one", owner="a"),
        "c/three": repo(full_name="c/three", owner="c", source="control:prose-only"),
    }
    assert cases.chosen(rows_, {}) == ["a/one"]


def test_a_repository_drawn_for_a_surface_outranks_an_ordinary_one() -> None:
    rows_ = {
        "a/one": repo(full_name="a/one", owner="a"),
        "z/two": repo(full_name="z/two", owner="z", source="surface:embed-content"),
    }
    assert cases.chosen(rows_, {})[0] == "z/two"


def test_the_selection_stops_at_the_case_count() -> None:
    rows_ = {
        f"o{index}/r": repo(
            full_name=f"o{index}/r", owner=f"o{index}", tests={"test_files": "tests/t.py"}
        )
        for index in range(30)
    }
    assert len(cases.chosen(rows_, {})) == cases.CASE_COUNT


def test_the_systematic_sample_fills_the_rest_and_never_repeats_a_row() -> None:
    rows_ = {
        f"o{index:02d}/r": repo(full_name=f"o{index:02d}/r", owner=f"o{index:02d}")
        for index in range(40)
    }
    picked = cases.chosen(rows_, {})
    assert len(picked) == cases.CASE_COUNT
    assert len(set(picked)) == cases.CASE_COUNT


def test_a_change_with_one_witness_takes_that_witness() -> None:
    finding = {
        "path": "app.py",
        "line": 1,
        "kind": "call",
        "symbol": "google.generativeai.embed_content",
        "scan_status": "eligible",
        "confidence_reason": "alias_resolved",
    }
    rows_ = {f"o{index}/r": repo(full_name=f"o{index}/r", owner=f"o{index}") for index in range(3)}
    picked = cases.chosen(rows_, {"o2/r": [finding]})
    assert "o2/r" in picked


def test_the_sole_witness_is_taken_even_when_the_sample_would_not_reach_it() -> None:
    pool = {
        f"o{index:02d}/r": repo(full_name=f"o{index:02d}/r", owner=f"o{index:02d}")
        for index in range(40)
    }
    pool["zz/witness"] = repo(full_name="zz/witness", owner="zz")
    found = {
        "zz/witness": [
            {
                "path": "a.py",
                "line": 1,
                "kind": "call",
                "symbol": "google.generativeai.delete_file",
                "scan_status": "eligible",
                "confidence_reason": "alias_resolved",
            }
        ]
    }
    assert cases.chosen(pool, found) == [
        "zz/witness",
        "o00/r",
        "o01/r",
        "o03/r",
        "o05/r",
        "o07/r",
        "o09/r",
        "o11/r",
        "o13/r",
        "o15/r",
        "o17/r",
        "o19/r",
        "o21/r",
        "o23/r",
        "o25/r",
        "o27/r",
        "o29/r",
        "o31/r",
        "o33/r",
        "o35/r",
    ]


def test_the_systematic_sample_takes_every_kth_row_and_not_the_first_k() -> None:
    """Ten suites fill ten slots; forty others fill the rest at a step of four."""
    pool = {
        f"t{index}/r": repo(
            full_name=f"t{index}/r", owner=f"t{index}", tests={"test_files": "t.py"}
        )
        for index in range(10)
    }
    pool.update(
        {
            f"o{index:02d}/r": repo(full_name=f"o{index:02d}/r", owner=f"o{index:02d}")
            for index in range(40)
        }
    )
    assert cases.chosen(pool, {}) == [
        "t0/r",
        "t1/r",
        "t2/r",
        "t3/r",
        "t4/r",
        "t5/r",
        "t6/r",
        "t7/r",
        "t8/r",
        "t9/r",
        "o00/r",
        "o04/r",
        "o08/r",
        "o12/r",
        "o16/r",
        "o20/r",
        "o24/r",
        "o28/r",
        "o32/r",
        "o36/r",
    ]


def test_at_least_a_third_of_each_stratum_is_holdout_and_no_owner_is_split() -> None:
    rows_ = {}
    for index in range(6):
        rows_[f"t{index}/r"] = repo(
            full_name=f"t{index}/r", owner=f"t{index}", tests={"test_files": "t.py"}
        )
    for index in range(12):
        rows_[f"p{index:02d}/r"] = repo(full_name=f"p{index:02d}/r", owner=f"p{index:02d}")
    picked = list(rows_)
    sides = cases.split(rows_, picked)
    assert set(sides.values()) <= set(cases.SPLITS)
    for stratum in (True, False):
        members = [name for name in picked if cases.testable(rows_[name]) is stratum]
        held = [name for name in members if sides[name] == "holdout"]
        assert len(held) * 3 >= len(members), stratum


def test_the_split_is_pinned_on_a_pool_whose_strata_would_disagree() -> None:
    """Unstratified, two of the three suites would land in holdout, not one."""
    rows_ = {
        f"t{index}/r": repo(
            full_name=f"t{index}/r", owner=f"t{index}", tests={"test_files": "t.py"}
        )
        for index in range(3)
    }
    rows_.update(
        {f"p{index}/r": repo(full_name=f"p{index}/r", owner=f"p{index}") for index in range(9)}
    )
    assert cases.split(rows_, list(rows_)) == {
        "t0/r": "dev",
        "t1/r": "holdout",
        "t2/r": "dev",
        "p0/r": "dev",
        "p1/r": "dev",
        "p2/r": "dev",
        "p3/r": "dev",
        "p4/r": "holdout",
        "p5/r": "dev",
        "p6/r": "holdout",
        "p7/r": "dev",
        "p8/r": "holdout",
    }


# Names chosen so `sha256` puts d026's two rows first and third: only then does counting the
# owner twice pass the holdout ceiling of four a row early. Any other order hides the bug.
DEDUP_POOL: tuple[tuple[str, str], ...] = (
    ("d026/a", "d026"),
    ("d026/b", "d026"),
    ("s39/a", "s39"),
    ("s56/a", "s56"),
    ("s25/a", "s25"),
    ("s08/a", "s08"),
    ("s46/a", "s46"),
    ("s09/a", "s09"),
    ("s47/a", "s47"),
    ("s13/a", "s13"),
    ("s55/a", "s55"),
    ("s50/a", "s50"),
)


def test_an_owner_with_two_cases_is_counted_once_and_lands_on_one_side() -> None:
    rows_ = {name: repo(full_name=name, owner=owner) for name, owner in DEDUP_POOL}
    assert cases.split(rows_, list(rows_)) == {
        "d026/a": "holdout",
        "d026/b": "holdout",
        "s39/a": "holdout",
        "s56/a": "holdout",
        "s25/a": "dev",
        "s08/a": "dev",
        "s46/a": "dev",
        "s09/a": "dev",
        "s47/a": "dev",
        "s13/a": "dev",
        "s55/a": "dev",
        "s50/a": "dev",
    }


def test_the_split_is_a_function_of_the_owner_name_and_nothing_else() -> None:
    rows_ = {f"o{index}/r": repo(full_name=f"o{index}/r", owner=f"o{index}") for index in range(6)}
    first = cases.split(rows_, list(rows_))
    assert cases.split(rows_, list(reversed(list(rows_)))) == first


def test_the_rule_table_says_no_when_a_rule_does_not_hold() -> None:
    bad = case(python="3.12", from_version=">=0.8", split="dev", pattern_key=["x"])
    table = "\n".join(cases._rule_table(corpus([bad])))
    assert "| Every case pins both SDK versions exactly | NO |" in table
    assert "| Every case names a full uv interpreter key | NO |" in table
    assert "| Every case's `pattern_key` is the one its ground truth names | NO |" in table
    assert f"| At least {cases.CASE_COUNT} cases | NO |" in table
    assert "| Every case carries a split, and at least a third are holdout | NO |" in table
    assert "| The negative controls exist, including both Vertex origins | NO |" in table


def test_the_rule_table_says_no_when_one_owner_has_three_cases() -> None:
    rows_ = [case(id=f"a__r{index}", full_name=f"a/r{index}", owner="a") for index in range(3)]
    table = "\n".join(cases._rule_table(corpus(rows_)))
    assert "| At most 2 cases share an owner | NO |" in table


def test_the_rule_table_says_no_when_only_one_vertex_origin_is_a_control() -> None:
    """The preview module is a second live `GenerativeModel`, not the same one."""
    one = corpus([case()], [control(control="vertex-generative-models")])
    assert "| The negative controls exist, including both Vertex origins | NO |" in "\n".join(
        cases._rule_table(one)
    )


def test_the_rule_table_says_yes_when_every_rule_holds() -> None:
    rows_ = []
    for index in range(cases.CASE_COUNT):
        rows_.append(
            case(
                id=f"o{index}__r",
                full_name=f"o{index}/r",
                owner=f"o{index}",
                split="holdout" if index < 7 else "dev",
            )
        )
    one = corpus(
        rows_,
        [control(control="vertex-preview"), control(control="vertex-generative-models")],
    )
    table = "\n".join(cases._rule_table(one))
    assert "NO" not in table


def test_the_case_table_prints_a_test_command_or_a_dash() -> None:
    table = "\n".join(
        cases._case_table(
            corpus([case(), case(id="b", full_name="b/c", owner="b", test_cmd="pytest -q")])
        )
    )
    assert "| -- |" in table
    assert "`pytest -q`" in table


def test_precision_is_undefined_rather_than_perfect_when_nothing_was_reported() -> None:
    """Reporting 100% for a tool that found nothing is the one flattering error."""
    empty = case(ground_truth={**case()["ground_truth"], "call_sites": []})
    text = "\n".join(cases._agreement_table(corpus([empty])))
    assert "Precision **--**, recall **--**" in text


def test_the_agreement_table_counts_a_miss_and_a_false_positive_separately() -> None:
    found = [
        {
            "path": "app.py",
            "line": 2,
            "kind": "call",
            "symbol": "google.generativeai.configure",
            "scan_status": "eligible",
            "confidence_reason": "alias_resolved",
        }
    ]
    text = "\n".join(cases._agreement_table(corpus([case()], findings_={"owner/repo": found})))
    assert "| `owner__repo` | 1 | 1 | 0 | 1 | 1 |" in text
    assert "| **all 1** | **1** | **1** | **0** | **1** | **1** |" in text
    assert "Precision **0.0%**, recall **0.0%**" in text


def test_the_totals_row_and_the_two_rates_come_from_the_matches() -> None:
    """One row of two matches and one miss: 100% precision, 66.7% recall."""
    two = [site(), site(line=2)]
    found = [
        {
            "path": "app.py",
            "line": line,
            "kind": "call",
            "symbol": "google.generativeai.configure",
            "scan_status": "eligible",
            "confidence_reason": "alias_resolved",
        }
        for line in (1, 2)
    ]
    one = case(ground_truth={**case()["ground_truth"], "call_sites": [*two, site(line=3)]})
    text = "\n".join(cases._agreement_table(corpus([one], findings_={"owner/repo": found})))
    assert "| `owner__repo` | 3 | 2 | 2 | 1 | 0 |" in text
    assert "| **all 1** | **3** | **2** | **2** | **1** | **0** |" in text
    assert "Precision **100.0%**, recall **66.7%**" in text


def test_a_module_named_as_a_string_never_enters_the_comparison() -> None:
    one = case(
        ground_truth={
            **case()["ground_truth"],
            "call_sites": [site(kind="dynamic", line=5)],
        }
    )
    assert sum(cases.labelled(one).values()) == 0
    text = "\n".join(cases._agreement_table(corpus([one])))
    assert "| `owner__repo` | 0 | 0 | 0 | 0 | 0 |" in text


def test_the_change_table_names_every_change_in_the_pack_and_counts_it() -> None:
    """One case naming `configure` twice: one change met, two call sites, the rest zero."""
    one = case(
        ground_truth={
            **case()["ground_truth"],
            "call_sites": [site(), site(line=2)],
        }
    )
    table = "\n".join(cases._change_table(corpus([one])))
    for change in CHANGES:
        assert f"| `{change}` |" in table
    assert "| `configure-to-client` | 1 | 2 |" in table
    assert "| `embed-content` | 0 | 0 |" in table


def test_the_control_table_prints_what_the_scanner_actually_reported() -> None:
    table = "\n".join(cases._control_table(corpus([case()], [control()])))
    assert "[other/repo](https://github.com/other/repo)" in table
    assert "`api.py:1`" in table


def test_the_draw_table_prints_a_list_a_single_name_and_a_dash() -> None:
    data = draws()
    data["controls"] = [
        {**data["controls"][0]},
        {
            "control": "prose-only",
            "shape": "s",
            "query": "q2",
            "hits": 5,
            "examined": 3,
            "outcome": "no_eligible_result",
            "drawn": None,
            "witness": None,
            "skipped": [{"full_name": "x/y", "reason": "unlicensed"}],
        },
    ]
    table = "\n".join(cases._draw_table(corpus([case()], draws_=data)))
    assert "`owner/repo`" in table
    assert "`other/repo`" in table
    assert "| -- | 1 unlicensed |" in table


def test_a_corpus_of_permissive_licences_says_every_case_may_keep_a_patch() -> None:
    assert "every case may keep one." in cases.render(corpus([case()]))


def test_a_copyleft_case_is_marked_metrics_only() -> None:
    one = corpus(
        [case()],
        repositories_={"owner/repo": repo(license="AGPL-3.0")},
    )
    assert "is metrics-only" in cases.render(one)


def test_the_block_needs_both_markers() -> None:
    begin, end = cases.MARKERS
    with pytest.raises(SystemExit):
        cases.block("no markers here")
    with pytest.raises(SystemExit):
        cases.block(f"{begin}\nbody\n")
    with pytest.raises(SystemExit):
        cases.block(f"body\n{end}")
    assert cases.block(f"{begin}\nbody\n{end}") == "body"


def test_main_prints_the_block_and_check_agrees_with_the_document() -> None:
    assert cases.main([]) == 0
    assert cases.main(["--check"]) == 0


def test_check_fails_on_a_stale_document(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stale = tmp_path / "CASES.md"
    begin, end = cases.MARKERS
    stale.write_text(f"{begin}\nold\n{end}\n", encoding="utf-8")
    monkeypatch.setattr(cases, "DOCUMENT", stale)
    assert cases.main(["--check"]) == 1


def test_a_missing_draw_file_leaves_the_corpus_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cases, "DRAWS", tmp_path / "nothing.yaml")
    assert "grapeot/devin.cursorrules" not in cases.repositories()


def test_a_scan_record_that_errored_is_not_read_as_findings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broken = tmp_path / "scan.json"
    broken.write_text(
        json.dumps({"scanned": [{"full_name": "x/y", "error": "timeout", "findings": []}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cases, "DRAWN_SCAN", broken)
    assert "x/y" not in cases.findings()


def test_a_missing_scan_file_is_skipped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cases, "DRAWN_SCAN", tmp_path / "gone.json")
    assert "GoogleCloudPlatform/Open_Data_QnA" not in cases.findings()


def test_there_are_at_least_twenty_cases_with_unique_ids() -> None:
    assert len(CASES) >= cases.CASE_COUNT
    assert len({entry["id"] for entry in CASES}) == len(CASES)


def test_every_case_id_is_the_slug_of_its_repository() -> None:
    for entry in CASES:
        assert entry["id"] == entry["full_name"].replace("/", "__")


def test_every_case_copies_the_corpus_faithfully() -> None:
    for entry in CASES:
        row = CORPUS.repositories[entry["full_name"]]
        assert entry["repo"] == row["url"]
        assert entry["sha"] == row["sha"]
        assert entry["license"] == row["license"]
        assert entry["owner"] == row["owner"]
        assert candidates.FULL_SHA.match(entry["sha"])
        assert row["license"] not in candidates.UNLICENSED
        assert not row["fork"]
        assert row["owner"] not in _dev_owners()


def _dev_owners() -> frozenset[str]:
    import gate1_collect

    return gate1_collect.DEV_CORPUS_OWNERS


def test_the_twenty_are_the_ones_the_rule_chooses() -> None:
    assert [entry["full_name"] for entry in CASES] == cases.chosen(
        CORPUS.repositories, CORPUS.findings
    )


def test_the_split_is_the_one_the_rule_computes() -> None:
    computed = cases.split(CORPUS.repositories, [entry["full_name"] for entry in CASES])
    assert {entry["full_name"]: entry["split"] for entry in CASES} == computed
    holdout = [entry for entry in CASES if entry["split"] == "holdout"]
    assert len(holdout) * 3 >= len(CASES)


def test_every_pattern_key_is_the_one_its_ground_truth_names() -> None:
    for entry in CASES:
        assert tuple(entry["pattern_key"]) == cases.ground_truth_key(entry)
        assert list(entry["pattern_key"]) == sorted(set(entry["pattern_key"]))


def test_every_case_names_the_provider_and_the_migration_the_pack_is() -> None:
    from run import DEFAULT_PACK

    provider, change = DEFAULT_PACK.split("/")
    for entry in CASES:
        assert entry["provider"] == provider
        assert entry["change"] == change


def test_every_case_pins_the_round_exactly_and_names_an_interpreter_that_exists() -> None:
    for entry in CASES:
        assert entry["from_version"] == CORPUS.cases["from_version"]
        assert entry["to_version"] == CORPUS.cases["to_version"]
        assert cases.EXACT_VERSION.match(entry["from_version"])
        assert cases.EXACT_VERSION.match(entry["to_version"])
        assert entry["python"] in INTERPRETERS
        assert cases.INTERPRETER_KEY.match(entry["python"])


def test_install_commands_exist_exactly_where_a_test_command_does() -> None:
    """ADR-041 D8: install exists to make `test_cmd` runnable, and for nothing else."""
    for entry in CASES:
        assert bool(entry["install"]) == bool(entry["test_cmd"])


def test_a_case_that_says_its_tests_cover_the_change_has_a_command_to_prove_it() -> None:
    for entry in CASES:
        if entry["ground_truth"]["tests_cover_change"]:
            assert entry["test_cmd"]


def test_no_case_needs_the_network_to_run_its_tests() -> None:
    """A suite that needs a credential gets no command at all, so the flag is never set."""
    for entry in CASES:
        assert entry["tests_require_network"] is False


def test_every_ground_truth_row_uses_the_vocabulary_and_explains_itself() -> None:
    for entry in CASES:
        truth = entry["ground_truth"]
        assert truth["files_read"]
        assert truth["what_it_is"]
        assert isinstance(truth["tests_cover_change"], bool)
        assert truth["tests_cover_change_why"]
        assert truth["call_sites"]
        for row in truth["call_sites"]:
            assert row["kind"] in KINDS, row
            assert row["label"] in cases.LABELS
            assert row["symbol"].startswith("google.generativeai")
            assert row["line"] >= 1
            assert cases.CALL_SITE.match(cases.rendered(row)), row
            if row["label"] == "manual":
                assert row.get("why"), row
        for row in truth["manifests"]:
            assert row["label"] in cases.LABELS
            assert row["symbol"] == "google-generativeai"
        for row in truth["must_not_report"]:
            assert row["why"]
            assert row["line"] >= 1


def test_every_case_names_a_reviewer_and_a_date() -> None:
    for entry in CASES:
        assert entry["reviewer"] == CORPUS.cases["reviewer"]
        assert ISO_DATE.match(entry["reviewed_at"])
        assert entry["notes"]


def test_a_file_a_call_site_names_was_read() -> None:
    for entry in CASES:
        read = set(entry["ground_truth"]["files_read"])
        for row in entry["ground_truth"]["call_sites"]:
            assert row["path"] in read, (entry["id"], row["path"])


def test_the_key_disagrees_with_the_scanner_somewhere() -> None:
    """A key copied from the scanner's output would agree everywhere (ADR-041 D1)."""
    missed = unexpected = 0
    for entry in CASES:
        key = cases.labelled(entry)
        found = rows(CORPUS.findings.get(entry["full_name"], []), ACTIONABLE_KINDS)
        missed += sum((key - found).values())
        unexpected += sum((found - key).values())
    assert missed > 0
    assert unexpected > 0


def test_a_pre_registered_miss_is_a_call_site_the_scan_does_not_report() -> None:
    """The recall hole gate 1 named: a wrapper module with no token."""
    entry = next(one for one in CASES if one["id"] == "AmineChr54__CleanVision-Futury_AI-Hackathon")
    key = cases.labelled(entry)
    found = rows(CORPUS.findings[entry["full_name"]], ACTIONABLE_KINDS)
    paths = {row.path for row in (key - found)}
    assert "backend/src/evaluation.py" in paths


def test_the_controls_are_confirmed_by_a_scan_and_not_by_a_search() -> None:
    for entry in CONTROLS:
        found = CORPUS.findings[entry["full_name"]]
        assert not [row for row in found if row["kind"] in cases.CONTROL_KINDS], entry["control"]
        assert entry["witness"]
        assert candidates.FULL_SHA.match(entry["sha"])
        assert entry["license"] not in candidates.UNLICENSED


def test_both_vertex_origins_are_controls() -> None:
    shapes = {entry["control"] for entry in CONTROLS}
    assert {"vertex-generative-models", "vertex-preview"} <= shapes


def test_no_control_is_also_a_case() -> None:
    assert not {entry["full_name"] for entry in CONTROLS} & {entry["full_name"] for entry in CASES}


def test_every_repository_t27_drew_obeys_the_corpus_rules() -> None:
    import gate1_collect

    owners: dict[str, int] = {}
    for row in CORPUS.draws["drawn"]:
        assert row["license"] not in candidates.UNLICENSED
        assert not row["fork"]
        assert row["owner"] not in gate1_collect.DEV_CORPUS_OWNERS
        assert row["size_kb"] <= gate1_collect.SIZE_CAP_KB
        assert CORPUS.findings.get(row["full_name"]) is not None
        owners[row["owner"]] = owners.get(row["owner"], 0) + 1
    assert max(owners.values()) <= candidates.MAX_PER_OWNER


def test_every_draw_publishes_a_dated_query_and_a_closed_skip_tally() -> None:
    entries = [CORPUS.draws["test_suites"], *CORPUS.draws["controls"]]
    for entry in entries:
        assert entry["query"]
        assert entry["outcome"] in candidates.OUTCOMES
        assert entry["examined"] <= entry["hits"] or entry["hits"] == 0
        for skipped in entry["skipped"]:
            assert skipped["reason"] in cases.DRAW_SKIP_REASONS, skipped


def test_a_drawn_test_suite_really_has_a_test_file() -> None:
    for name in CORPUS.draws["test_suites"]["drawn"]:
        assert cases.testable(CORPUS.repositories[name])


def test_the_document_publishes_every_case_and_every_control() -> None:
    text = cases.DOCUMENT.read_text(encoding="utf-8")
    for entry in CASES:
        assert entry["repo"] in text
        assert entry["id"] in text
    for entry in CONTROLS:
        assert entry["full_name"] in text


def test_the_document_links_the_decision_behind_it() -> None:
    text = cases.DOCUMENT.read_text(encoding="utf-8")
    assert "ADR-041-case-definitions-split.md" in text
    assert (ROOT / "docs" / "adr").joinpath("ADR-041-case-definitions-split.md").exists()


def test_the_published_block_is_the_one_the_renderer_produces() -> None:
    assert cases.block(cases.DOCUMENT.read_text(encoding="utf-8")) == cases.render(CORPUS)
