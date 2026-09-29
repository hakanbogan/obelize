"""The round block is re-rendered, never read back; hand-built rounds reach what round 1 cannot."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from platforms import BENCH

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import run  # noqa: E402
import summarize  # noqa: E402

pytestmark = BENCH

DOCUMENT = ROOT / "docs" / "BENCHMARK_RESULTS.md"


def case(identifier: str, split: str = "dev", control: bool = False, **over: Any) -> run.Case:
    fields: dict[str, Any] = {
        "id": identifier,
        "origin": "corpus",
        "control": control,
        "split": None if control else split,
        "repo": "https://example.invalid/r",
        "sha": "0" * 40,
        "python": "cpython-3.12.9-macos-aarch64-none",
        "from_version": "0.8.6",
        "to_version": "2.24.0",
        "install": (),
        "test_cmd": "pytest -q",
        "ground_truth": {
            "call_sites": [
                {
                    "path": "app.py",
                    "line": 1,
                    "kind": "import",
                    "symbol": "google.generativeai",
                    "label": "auto",
                }
            ],
            "manifests": [],
            "must_not_report": [],
            "tests_cover_change": True,
        },
        "review": {},
        "source": None,
    }
    fields.update(over)
    return run.Case(**fields)


def record(
    identifier: str, tier: str = "partial", error: Any = None, **over: Any
) -> dict[str, Any]:
    measurements = {
        "detected": 4,
        "false_positive": 0,
        "missed_call_site": 1,
        "unmigrated": 2,
        "patch_applied": True,
        "patch_compiles": True,
        "false_positive_edit": 0,
        "human_edits": None,
        "runtime_seconds": 1.5,
        "tests_baseline": {"status": "not_run", "passed": None, "failed": None, "skipped": None},
        "tests_after": {"status": "not_run", "passed": None, "failed": None, "skipped": None},
    }
    measurements.update(over.pop("measurements", {}))
    body: dict[str, Any] = {
        "schema_version": run.RESULT_SCHEMA_VERSION,
        "case": identifier,
        "tier": tier,
        "error": error,
        "measurements": measurements,
        "provenance": {"obelize_version": "0.1.0.dev0", "pack_sha256": "a" * 64},
    }
    body.update(over)
    return body


def a_round(cases: list[run.Case], results: list[dict[str, Any]] | None = None) -> summarize.Round:
    return summarize.Round(1, cases, {row["case"]: row for row in results or []})


def test_the_published_block_is_what_the_generator_renders() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")
    assert summarize.block(text) == summarize.render(summarize.load())


def test_a_document_with_no_markers_is_refused() -> None:
    with pytest.raises(SystemExit, match="no round block"):
        summarize.block("# nothing here")


def test_a_document_with_only_a_beginning_is_refused() -> None:
    with pytest.raises(SystemExit, match="no round block"):
        summarize.block(summarize.MARKERS[0] + "\nhalf a block\n")


def test_check_passes_on_the_committed_document(capsys: pytest.CaptureFixture[str]) -> None:
    assert summarize.main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_check_fails_when_the_document_no_longer_matches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(summarize, "render", lambda state: "something else entirely")
    assert summarize.main(["--check"]) == 1
    assert "stale" in capsys.readouterr().out


def test_with_no_flag_the_block_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    assert summarize.main([]) == 0
    assert "Round 1, from `bench/cases.yaml`" in capsys.readouterr().out


def test_every_case_and_control_in_the_round_has_a_published_result() -> None:
    state = summarize.load()
    assert sorted(state.results) == sorted(subject.id for subject in state.cases)
    assert len(state.results) == 23


def test_every_published_result_is_the_shape_this_reads() -> None:
    for record in summarize.load().results.values():
        assert record["schema_version"] == run.RESULT_SCHEMA_VERSION
        assert record["tier"] in run.TIERS
        if record["error"] is not None:
            assert record["error"]["reason"] in run.ERROR_REASONS


def test_no_published_result_carries_an_absolute_path() -> None:
    folder = run.RESULTS / "round-1"
    for path in sorted(folder.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text, path.name
        assert "/home/" not in text, path.name
        assert str(run.ROOT) not in text, path.name


def test_a_round_that_has_not_run_has_no_results(tmp_path: Path) -> None:
    assert summarize.load(tmp_path / "nothing").results == {}


def test_every_result_file_in_the_round_directory_is_read(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(json.dumps(record("a")))
    (tmp_path / "b.json").write_text(json.dumps(record("b")))
    assert sorted(summarize.load(tmp_path).results) == ["a", "b"]


def test_a_result_written_by_another_shape_is_refused_rather_than_read(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(json.dumps({**record("a"), "schema_version": 99}))
    with pytest.raises(SystemExit, match="schema_version 99"):
        summarize.load(tmp_path)


def test_the_round_number_comes_from_the_case_file() -> None:
    assert summarize.load().number == 1


def test_a_control_is_not_graded() -> None:
    state = a_round([case("a"), case("c", control=True)])
    assert [subject.id for subject in summarize.graded(state)] == ["a"]


def test_two_cases_with_the_same_symbols_are_one_pattern() -> None:
    state = a_round([case("a"), case("b")])
    assert len(summarize.patterns(state)) == 1


def test_a_case_with_different_symbols_is_a_different_pattern() -> None:
    other = case("b")
    other.ground_truth["call_sites"][0]["symbol"] = "google.generativeai.configure"
    assert len(summarize.patterns(a_round([case("a"), other]))) == 2


def test_a_manifest_row_is_part_of_the_pattern_key() -> None:
    other = case("b")
    other.ground_truth["manifests"].append(
        {"path": "requirements.txt", "line": 1, "symbol": "google-generativeai", "label": "auto"}
    )
    assert len(summarize.patterns(a_round([case("a"), other]))) == 2


def test_a_case_with_no_result_has_no_tier() -> None:
    state = a_round([case("a")], [])
    assert summarize.tier_of(state, state.cases[0]) is None


def test_a_case_with_a_result_has_the_tier_that_result_carries() -> None:
    state = a_round([case("a")], [record("a", "wrong")])
    assert summarize.tier_of(state, state.cases[0]) == "wrong"


def test_the_summary_row_says_the_round_has_not_been_run() -> None:
    rendered = summarize.render(a_round([case("a"), case("b", "holdout")]))
    assert "| 1 | 2 | 1 / 1 | 1 | 0 | none -- the round has not been run |" in rendered


def test_the_summary_row_names_what_the_results_were_measured_with() -> None:
    rendered = summarize.render(a_round([case("a")], [record("a")]))
    assert "1, obelize 0.1.0.dev0, pack `aaaaaaaaaaaaaaaa...`" in rendered


def test_the_ceiling_table_names_what_caps_each_case() -> None:
    reachable = [case("a"), case("b", "holdout")]
    rendered = summarize.render(a_round([*reachable, case("c", test_cmd=None)]))
    assert "| `a` | dev | yes | -- |" in rendered
    assert "| `b` | holdout | yes | -- |" in rendered
    assert "| `c` | dev | no | no test command |" in rendered
    assert "| **Total** | | **2 of 3** |" in rendered


def test_the_ceiling_table_tallies_the_reasons() -> None:
    rendered = summarize.render(a_round([case("a", test_cmd=None), case("b", test_cmd=None)]))
    assert "2 no test command" in rendered


def test_a_control_is_in_no_rate_and_in_its_own_table() -> None:
    state = a_round([case("a"), case("c", control=True)], [record("a"), record("c", "unsupported")])
    rendered = summarize.render(state)
    assert "| `c` | no call site and no pin | `unsupported` | 4 | 0 |" in rendered
    assert "| `a` | dev | `partial` |" in rendered
    assert "| Cases | 1 | 0 | 0.0% |" in rendered


def test_a_control_with_no_result_is_still_listed() -> None:
    rendered = summarize.render(a_round([case("a"), case("c", control=True)]))
    assert "| `c` | no call site and no pin | -- | -- | -- |" in rendered


def test_the_rate_is_reported_over_cases_and_over_patterns() -> None:
    other = case("b", "holdout")
    other.ground_truth["call_sites"][0]["symbol"] = "google.generativeai.configure"
    state = a_round([case("a"), other], [record("a", "verified_success"), record("b", "partial")])
    rendered = summarize.render(state)
    assert "| Cases | 2 | 1 | 50.0% |" in rendered
    assert "| Cases (dev) | 1 | 1 | 100.0% |" in rendered
    assert "| Cases (holdout) | 1 | 0 | 0.0% |" in rendered
    assert "| Unique patterns | 2 | 1 | 50.0% |" in rendered


def test_the_pattern_rate_is_reported_per_side_as_well() -> None:
    other = case("b", "holdout")
    other.ground_truth["call_sites"][0]["symbol"] = "google.generativeai.configure"
    state = a_round([case("a"), other], [record("a", "verified_success"), record("b", "partial")])
    rendered = summarize.render(state)
    assert "| Unique patterns | 2 | 1 | 50.0% |" in rendered
    assert "| Unique patterns (dev) | 1 | 1 | 100.0% |" in rendered
    assert "| Unique patterns (holdout) | 1 | 0 | 0.0% |" in rendered


def test_a_pattern_both_sides_carry_is_counted_on_both_sides() -> None:
    """Split rows need not sum to the total: a pattern in both splits counts on each side."""
    state = a_round(
        [case("a"), case("b", "holdout")],
        [record("a", "verified_success"), record("b", "partial")],
    )
    rendered = summarize.render(state)
    assert "| Unique patterns | 1 | 1 | 100.0% |" in rendered
    assert "| Unique patterns (dev) | 1 | 1 | 100.0% |" in rendered
    assert "| Unique patterns (holdout) | 1 | 0 | 0.0% |" in rendered


def test_a_side_that_ran_nothing_has_no_pattern_denominator() -> None:
    state = a_round([case("a"), case("b", "holdout")], [record("a", "partial")])
    assert "| Unique patterns (holdout) | 0 | 0 | -- |" in summarize.render(state)


def test_a_pattern_counts_once_however_many_cases_carry_it() -> None:
    state = a_round(
        [case("a"), case("b")], [record("a", "verified_success"), record("b", "verified_success")]
    )
    rendered = summarize.render(state)
    assert "| Cases | 2 | 2 | 100.0% |" in rendered
    assert "| Unique patterns | 1 | 1 | 100.0% |" in rendered


def test_a_pattern_one_of_whose_cases_succeeded_is_a_pattern_that_succeeded() -> None:
    """Grouping stops one shape inflating the numerator; it is not a veto."""
    state = a_round(
        [case("a"), case("b")], [record("a", "verified_success"), record("b", "partial")]
    )
    rendered = summarize.render(state)
    assert "| Cases | 2 | 1 | 50.0% |" in rendered
    assert "| Unique patterns | 1 | 1 | 100.0% |" in rendered


def test_a_pattern_no_case_of_which_has_run_is_not_in_the_denominator() -> None:
    other = case("b")
    other.ground_truth["call_sites"][0]["symbol"] = "google.generativeai.configure"
    state = a_round([case("a"), other], [record("a", "partial")])
    assert "| Unique patterns | 1 | 0 | 0.0% |" in summarize.render(state)


def test_a_case_that_has_not_run_is_in_no_denominator() -> None:
    state = a_round([case("a"), case("b", "holdout")], [record("a", "verified_success")])
    assert "| Cases | 1 | 1 | 100.0% |" in summarize.render(state)
    assert "| Cases (holdout) | 0 | 0 | -- |" in summarize.render(state)


def test_every_tier_gets_a_row_whether_or_not_anything_reached_it() -> None:
    state = a_round([case("a"), case("b", "holdout")], [record("a", "wrong"), record("b", "wrong")])
    rendered = summarize.render(state)
    assert "| `wrong` | 1 | 1 | 2 |" in rendered
    assert "| `verified_success` | 0 | 0 | 0 |" in rendered
    for tier in run.TIERS:
        assert f"| `{tier}` |" in rendered


def test_the_case_table_publishes_the_ones_that_went_wrong_too() -> None:
    state = a_round([case("a")], [record("a", "wrong", measurements={"false_positive": 3})])
    rendered = summarize.render(state)
    assert "| `a` | dev | `wrong` | 4 | 3 | 1 | 2 | -- | 1.5 |" in rendered


def test_the_case_table_totals_every_column_it_can() -> None:
    state = a_round(
        [case("a"), case("b", "holdout")],
        [record("a"), record("b", measurements={"detected": 6, "missed_call_site": 0})],
    )
    assert "| **Total** | | | **10** | **0** | **1** | **4** | | **3.0** |" in summarize.render(
        state
    )


def test_a_suite_that_never_ran_is_in_no_suite_table() -> None:
    assert "**What the suites did.**" not in summarize.render(a_round([case("a")], [record("a")]))


def test_a_suite_that_ran_says_what_it_skipped() -> None:
    """A `pass` that skipped nineteen of twenty-one is what this column is for."""
    ran = record(
        "a",
        measurements={
            "tests_baseline": {"status": "pass", "passed": 2, "failed": 0, "skipped": 19},
            "tests_after": {"status": "pass", "passed": 2, "failed": 0, "skipped": 19},
        },
    )
    rendered = summarize.render(a_round([case("a")], [ran]))
    assert "**What the suites did.**" in rendered
    assert "| `a` | `pass` | 2 / 0 / 19 | `pass` | 2 / 0 / 19 |" in rendered


def test_a_suite_with_no_junit_report_prints_one_dash_and_not_three() -> None:
    ran = record(
        "a",
        measurements={
            "tests_baseline": {"status": "pass", "passed": None, "failed": None, "skipped": None},
            "tests_after": {"status": "fail", "passed": None, "failed": None, "skipped": None},
        },
    )
    assert "| `a` | `pass` | -- | `fail` | -- |" in summarize.render(a_round([case("a")], [ran]))


def test_a_human_edit_count_nobody_has_filled_in_is_a_dash() -> None:
    state = a_round([case("a")], [record("a", measurements={"human_edits": 0})])
    assert "| 0 | 1.5 |" in summarize.render(state)
    assert "| -- | 1.5 |" in summarize.render(a_round([case("a")], [record("a")]))


def test_a_case_with_no_result_is_not_a_row_in_the_case_table() -> None:
    state = a_round([case("a"), case("b")], [record("a")])
    rendered = summarize.render(state)
    assert "| `a` | dev | `partial` |" in rendered
    assert "| `b` | dev | `" not in rendered


def test_an_error_is_published_with_the_step_it_happened_at() -> None:
    failed = record("a", "error", error={"step": "venv", "reason": "venv_failed", "detail": "no"})
    rendered = summarize.render(a_round([case("a")], [failed]))
    assert "| `a` | `venv` | `venv_failed` | no |" in rendered
    assert "**What errored.**" in rendered


def test_a_round_in_which_nothing_errored_has_no_error_table() -> None:
    assert "**What errored.**" not in summarize.render(a_round([case("a")], [record("a")]))


def test_the_tables_that_need_results_say_so_when_there_are_none() -> None:
    rendered = summarize.render(a_round([case("a")]))
    assert rendered.count("_None: no case has been run._") == 3


def test_a_rate_over_nothing_is_not_zero_percent() -> None:
    assert summarize._share(0, 0) == "--"
    assert summarize._share(1, 3) == "33.3%"
