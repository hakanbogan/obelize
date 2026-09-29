"""Error analysis: published block, two-way cause/disposition contract, and the lever model.

The lever model must reproduce round one's published numbers from a different record.
"""

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

import errors  # noqa: E402
import errors_collect  # noqa: E402
import run  # noqa: E402

pytestmark = BENCH

DOCUMENT = ROOT / "docs" / "BENCHMARK_RESULTS.md"
COVERAGE = ROOT / "tests" / "fixtures" / "scan" / "COVERAGE.md"

# The dispositions `docs/BENCHMARK.md` promises; reading `errors.DISPOSITIONS` would be vacuous.
PROMISED = {"rule_change", "scan_change", "limitation"}

# The classes a cause may have, written out for the same reason.
CLASSES = {"withheld", "derived", "missed", "unexpected"}

# The two codes ADR-010 raises about a neighbouring row, not the row itself.
DERIVED = {"file_not_fully_migrated", "repo_not_fully_migrated"}

# Round one as `bench/results/round-1/` publishes it, copied rather than computed.
ROUND_ONE_ROWS = 277
ROUND_ONE_MIGRATED = 34
ROUND_ONE_CEILING = 252

# Pinned by hand: the largest levers, and the second-commonest bail, which is worth nothing.
LARGEST_LEVERS = {"local_import": 26, "generation_config_not_static": 26}
WORTHLESS = "multiple_configure_calls"


def a_case(identifier: str, **over: Any) -> run.Case:
    fields: dict[str, Any] = {
        "id": identifier,
        "origin": "corpus",
        "control": False,
        "split": "dev",
        "repo": "https://example.invalid/r",
        "sha": "0" * 40,
        "python": "cpython-3.12.9-macos-aarch64-none",
        "from_version": "0.8.6",
        "to_version": "2.24.0",
        "install": (),
        "test_cmd": None,
        "ground_truth": {"call_sites": [], "manifests": [], "must_not_report": []},
        "review": {},
        "source": None,
    }
    fields.update(over)
    return run.Case(**fields)


def a_row(path: str, line: int, symbol: str, kind: str = "call") -> dict[str, Any]:
    return {"path": path, "line": line, "kind": kind, "symbol": symbol, "label": "auto"}


def an_analysis(
    cases: list[run.Case],
    record: dict[str, Any] | None = None,
    key: dict[str, Any] | None = None,
) -> errors.Analysis:
    return errors.Analysis(1, cases, {"cases": record or {}}, key or {})


def per_case(
    findings: list[dict[str, Any]] | None = None,
    withheld: list[dict[str, Any]] | None = None,
    applied: list[list[Any]] | None = None,
) -> dict[str, Any]:
    return {
        "run_id": "20260921T000000Z-abcdef12",
        "exit_code": 4,
        "findings": findings or [],
        "withheld": withheld or [],
        "applied": applied or [],
    }


def test_the_published_block_is_what_the_generator_renders() -> None:
    assert errors.block(DOCUMENT.read_text(encoding="utf-8")) == errors.render(errors.load())


def test_a_document_with_no_markers_is_refused() -> None:
    with pytest.raises(SystemExit, match="no errors block"):
        errors.block("# nothing here")


def test_a_document_with_only_a_beginning_is_refused() -> None:
    with pytest.raises(SystemExit, match="no errors block"):
        errors.block(errors.MARKERS[0] + "\nhalf a block\n")


def test_check_passes_on_the_committed_document(capsys: pytest.CaptureFixture[str]) -> None:
    assert errors.main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_check_fails_when_the_document_no_longer_matches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(errors, "render", lambda state: "something else entirely")
    assert errors.main(["--check"]) == 1
    assert "stale" in capsys.readouterr().out


def test_with_no_flag_the_block_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    assert errors.main([]) == 0
    assert "Round 1, from `bench/cases.yaml`" in capsys.readouterr().out


def test_a_round_with_no_collected_record_says_so_rather_than_printing_zeroes() -> None:
    rendered = errors.render(an_analysis([a_case("only")]))
    assert rendered == "_None: round 1 has no collected record._"


def test_a_round_number_with_no_record_file_is_not_an_error() -> None:
    assert errors.load(99).record["cases"] == {}


def test_every_row_every_key_names_has_exactly_one_state() -> None:
    state = errors.load()
    found = errors.rows(state)
    expected = sum(len(run.expected_rows(case)) for case in errors.graded(state))
    assert len(found) == expected == ROUND_ONE_ROWS
    assert {row.state for row in found} <= {"migrated", "withheld", "derived", "missed"}


def test_the_migrated_count_is_the_one_the_round_published() -> None:
    state = errors.load()
    migrated = sum(1 for row in errors.rows(state) if row.state == "migrated")
    published = sum(
        int(json.loads(path.read_text(encoding="utf-8"))["measurements"]["unmigrated"])
        for path in sorted((run.RESULTS / "round-1").glob("*.json"))
    )
    assert migrated == ROUND_ONE_MIGRATED
    assert ROUND_ONE_ROWS - migrated == published


def test_the_simulation_with_nothing_lifted_is_the_round_itself() -> None:
    state = errors.load()
    assert (
        sum(errors.migrated(state, case, frozenset()) for case in errors.graded(state))
        == ROUND_ONE_MIGRATED
    )


def test_lifting_every_bail_stops_exactly_at_the_rows_nothing_reported() -> None:
    state = errors.load()
    missed = sum(1 for row in errors.rows(state) if row.state == "missed")
    assert errors.ceiling(state) == ROUND_ONE_CEILING
    assert ROUND_ONE_ROWS - errors.ceiling(state) == missed


def test_a_row_a_case_has_no_record_for_is_not_counted() -> None:
    case = a_case("absent", ground_truth={"call_sites": [a_row("a.py", 1, "x")], "manifests": []})
    state = an_analysis([case])
    assert errors.rows(state) == []
    assert errors.migrated(state, case, frozenset()) == 0
    assert errors.unexpected(state) == []


def test_a_control_is_not_in_the_analysis() -> None:
    state = errors.load()
    assert {case.id for case in errors.graded(state)} == {
        case.id for case in state.cases if not case.control
    }
    assert len(errors.graded(state)) == 20


def test_every_cause_the_round_holds_has_a_disposition() -> None:
    state = errors.load()
    for cause in errors.observed(state):
        assert errors.disposition(state, cause)["disposition"] in PROMISED


def test_every_finding_no_key_claims_has_a_disposition() -> None:
    state = errors.load()
    causes = errors.unexpected_causes(state)
    for case_id, row in errors.unexpected(state):
        cause = causes[f"{case_id}:{row.path}:{row.line}"]
        assert errors.disposition(state, cause)["disposition"] in PROMISED


def test_no_disposition_names_a_cause_the_round_does_not_hold() -> None:
    state = errors.load()
    used = set(errors.observed(state)) | set(errors.unexpected_causes(state).values())
    assert set(state.key["causes"]) == used


def test_a_cause_with_no_disposition_is_refused() -> None:
    state = an_analysis([], key={"causes": {}})
    with pytest.raises(SystemExit, match="no disposition for 'invented'"):
        errors.disposition(state, "invented")


def test_every_cause_is_classed_and_the_class_matches_the_rows_it_covers() -> None:
    state = errors.load()
    classes = {row.cause: row.state for row in errors.rows(state) if row.cause is not None}
    for cause, entry in state.key["causes"].items():
        assert entry["class"] in CLASSES
        if cause in classes:
            assert entry["class"] == classes[cause]


def test_the_two_atomicity_codes_are_the_only_derived_ones() -> None:
    state = errors.load()
    derived = {c for c, e in state.key["causes"].items() if e["class"] == "derived"}
    assert derived == DERIVED
    assert {row.cause for row in errors.rows(state) if row.state == "derived"} == DERIVED


def test_a_limitation_names_an_adr_that_exists() -> None:
    state = errors.load()
    for cause, entry in state.key["causes"].items():
        if entry["disposition"] != "limitation":
            continue
        number = re.fullmatch(r"ADR-(\d{3})", str(entry["recorded"]))
        assert number is not None, f"{cause}: {entry['recorded']!r} is not an ADR"
        assert list(ROOT.glob(f"docs/adr/ADR-{number.group(1)}-*.md")), cause


def test_a_change_names_a_coverage_gap_that_is_open() -> None:
    text = COVERAGE.read_text(encoding="utf-8")
    state = errors.load()
    for cause, entry in state.key["causes"].items():
        if entry["disposition"] == "limitation":
            continue
        number = re.fullmatch(r"COVERAGE (\d{1,2})", str(entry["recorded"]))
        assert number is not None, f"{cause}: {entry['recorded']!r} is not a gap"
        heading = f"\n{number.group(1)}. "
        assert heading in text, cause
        assert f"{heading}~~" not in text, f"{cause}: gap {number.group(1)} is closed"


def test_the_hand_written_misses_are_exactly_the_rounds_misses() -> None:
    state = errors.load()
    missed = {
        (row.case, row.path, row.line, row.symbol)
        for row in errors.rows(state)
        if row.state == "missed"
    }
    assert set(errors.miss_causes(state)) == missed
    assert len(missed) == 25


def test_a_miss_with_no_hand_written_cause_carries_none() -> None:
    case = a_case("unlisted", ground_truth={"call_sites": [a_row("a.py", 1, "x")], "manifests": []})
    state = an_analysis([case], {"unlisted": per_case()})
    assert errors.rows(state) == [errors.Row("unlisted", "a.py", 1, "x", "missed", None)]


def test_a_key_with_no_misses_and_no_unexpected_entries_reads_as_empty() -> None:
    state = an_analysis([], key={})
    assert errors.miss_causes(state) == {}
    assert errors.unexpected_causes(state) == {}


def test_the_two_largest_levers_are_the_ones_the_analysis_names() -> None:
    state = errors.load()
    for cause, expected in LARGEST_LEVERS.items():
        assert errors.lever(state, cause) == expected
    assert max(errors.lever(state, cause) for cause in errors.observed(state)) == 26


def test_the_second_commonest_bail_is_worth_nothing_on_its_own() -> None:
    state = errors.load()
    counted = errors.observed(state)
    ranked = sorted(counted, key=lambda cause: (-counted[cause], cause))
    assert ranked[1] == WORTHLESS
    assert errors.lever(state, WORTHLESS) == 0


def test_two_bails_in_one_file_buy_nothing_apart_and_the_file_together() -> None:
    """Why the lever column has no total."""
    case = a_case(
        "both",
        ground_truth={
            "call_sites": [a_row("a.py", 1, "one"), a_row("a.py", 2, "two")],
            "manifests": [],
        },
    )
    withheld = [
        {"path": "a.py", "line": 1, "symbol": "one", "bail": "first", "caused_by": None},
        {"path": "a.py", "line": 2, "symbol": "two", "bail": "second", "caused_by": None},
    ]
    state = an_analysis([case], {"both": per_case(withheld=withheld)})
    assert errors.lever(state, "first") == 0
    assert errors.lever(state, "second") == 0
    assert errors.migrated(state, case, frozenset({"first", "second"})) == 2


def test_lifting_the_last_bail_in_a_repository_buys_the_manifest_row_too() -> None:
    case = a_case(
        "manifest",
        ground_truth={
            "call_sites": [a_row("a.py", 1, "one")],
            "manifests": [{"path": "r.txt", "line": 3, "symbol": "google-generativeai"}],
        },
    )
    withheld = [
        {"path": "a.py", "line": 1, "symbol": "one", "bail": "only", "caused_by": None},
        {
            "path": "r.txt",
            "line": 3,
            "symbol": "google-generativeai",
            "bail": "repo_not_fully_migrated",
            "caused_by": None,
        },
    ]
    state = an_analysis([case], {"manifest": per_case(withheld=withheld)})
    assert errors.lever(state, "only") == 2


def test_a_manifest_row_needs_every_file_and_not_one_of_them() -> None:
    """ADR-010 F-2 is repository-wide: one unblocked file does not migrate the pin."""
    case = a_case(
        "two_files",
        ground_truth={
            "call_sites": [a_row("a.py", 1, "one"), a_row("b.py", 1, "two")],
            "manifests": [{"path": "r.txt", "line": 3, "symbol": "google-generativeai"}],
        },
    )
    withheld = [
        {"path": "a.py", "line": 1, "symbol": "one", "bail": "first", "caused_by": None},
        {"path": "b.py", "line": 1, "symbol": "two", "bail": "second", "caused_by": None},
        {
            "path": "r.txt",
            "line": 3,
            "symbol": "google-generativeai",
            "bail": "repo_not_fully_migrated",
            "caused_by": None,
        },
    ]
    state = an_analysis([case], {"two_files": per_case(withheld=withheld)})
    assert errors.migrated(state, case, frozenset({"first"})) == 1
    assert errors.migrated(state, case, frozenset({"first", "second"})) == 3


def test_a_file_the_run_wrote_needs_no_lift() -> None:
    case = a_case(
        "written", ground_truth={"call_sites": [a_row("a.py", 1, "one")], "manifests": []}
    )
    state = an_analysis([case], {"written": per_case(applied=[["a.py", 1]])})
    assert errors.migrated(state, case, frozenset()) == 1
    assert errors.blockers(state, case) == {}


def test_a_derived_row_migrates_only_with_the_file_it_sits_in() -> None:
    case = a_case(
        "derived",
        ground_truth={
            "call_sites": [a_row("a.py", 1, "one"), a_row("a.py", 2, "two")],
            "manifests": [],
        },
    )
    withheld = [
        {"path": "a.py", "line": 1, "symbol": "one", "bail": "blocker", "caused_by": None},
        {
            "path": "a.py",
            "line": 2,
            "symbol": "two",
            "bail": "file_not_fully_migrated",
            "caused_by": ["blocker"],
        },
    ]
    state = an_analysis([case], {"derived": per_case(withheld=withheld)})
    assert errors.migrated(state, case, frozenset()) == 0
    assert errors.migrated(state, case, frozenset({"blocker"})) == 2


def test_a_case_with_no_record_has_no_blockers() -> None:
    assert errors.blockers(an_analysis([]), a_case("gone")) == {}


def test_the_unexpected_rows_are_the_false_positives_the_round_published() -> None:
    state = errors.load()
    published = sum(
        int(json.loads(path.read_text(encoding="utf-8"))["measurements"]["false_positive"])
        for path in sorted((run.RESULTS / "round-1").glob("*.json"))
    )
    assert len(errors.unexpected(state)) == published == 3


def test_a_round_with_nothing_unexpected_prints_no_such_table() -> None:
    case = a_case("clean", ground_truth={"call_sites": [a_row("a.py", 1, "one")], "manifests": []})
    finding = {"path": "a.py", "line": 1, "kind": "call", "symbol": "one"}
    state = an_analysis([case], {"clean": per_case(findings=[finding], applied=[["a.py", 1]])})
    assert "no key claims" not in errors.render(state)


def test_a_case_the_round_did_not_reach_is_in_no_table() -> None:
    ran = a_case("ran", ground_truth={"call_sites": [a_row("a.py", 1, "one")], "manifests": []})
    skipped = a_case("skipped", ground_truth={"call_sites": [a_row("b.py", 2, "two")]})
    state = an_analysis([ran, skipped], {"ran": per_case(applied=[["a.py", 1]])})
    rendered = errors.render(state)
    assert "`ran`" in rendered
    assert "`skipped`" not in rendered


def test_a_share_of_nothing_is_a_dash_and_not_a_zero() -> None:
    assert errors._share(0, 0) == "--"
    assert errors._share(1, 4) == "25.0%"


def write_work_tree(
    root: Path, case_id: str, sha: str, *, runs: int = 1, pack: str = "p" * 64
) -> Path:
    checkout = root / case_id
    for index in range(runs):
        folder = checkout / ".obelize" / "runs" / f"2026092{index}T000000Z-abcdef12"
        folder.mkdir(parents=True)
        (folder / "run.json").write_text(
            json.dumps(
                {
                    "run_id": folder.name,
                    "exit_code": 4,
                    "git_sha": sha,
                    "obelize_version": "0.1.0.dev0",
                    "pack": {"sha256": pack},
                    "withheld": [
                        {
                            "path": "a.py",
                            "line": 1,
                            "symbol": "one",
                            "bail": "only",
                            "caused_by": None,
                            "extra": "dropped",
                        }
                    ],
                    "file_edits": [{"path": "b.py"}],
                }
            ),
            encoding="utf-8",
        )
        (folder / "plan.json").write_text(
            json.dumps(
                {
                    "edits": [
                        {"path": "b.py", "line": 9, "status": "auto"},
                        # `auto`, but in a file `file_edits` omits, so it did not land.
                        {"path": "c.py", "line": 4, "status": "auto"},
                    ]
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        (folder / "findings.json").write_text(
            json.dumps(
                {
                    "findings": [
                        {
                            "path": "a.py",
                            "line": 1,
                            "column": 4,
                            "kind": "call",
                            "symbol": "one",
                            "confidence_reason": "alias_resolved",
                            "scan_status": "needs_review",
                            "bail": "only",
                            "evidence": "genai.configure(api_key=SECRET)",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
    return checkout


@pytest.fixture
def collected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """One case, one run folder, and a published result that agrees with it."""
    case = a_case("one__case", sha="a" * 40)
    monkeypatch.setattr(run, "corpus", lambda: [case])
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    monkeypatch.setattr(run, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(errors_collect, "RESULTS", tmp_path / "out")
    (tmp_path / "results" / "round-1").mkdir(parents=True)
    (tmp_path / "results" / "round-1" / "one__case.json").write_text(
        json.dumps(
            {
                "case": "one__case",
                "provenance": {"obelize_version": "0.1.0.dev0", "pack_sha256": "p" * 64},
            }
        ),
        encoding="utf-8",
    )
    write_work_tree(tmp_path / "work" / "round-1", "one__case", "a" * 40)
    return tmp_path


def test_a_collected_record_keeps_the_fields_the_analysis_reads(collected: Path) -> None:
    document = errors_collect.collect(1)
    case = document["cases"]["one__case"]
    assert case["withheld"] == [
        {"path": "a.py", "line": 1, "symbol": "one", "bail": "only", "caused_by": None}
    ]
    assert case["applied"] == [["b.py", 9]]
    assert case["run_id"].endswith("-abcdef12")


def test_an_edit_planned_into_a_file_the_run_refused_did_not_land(collected: Path) -> None:
    """A plan is what obelize would do and `file_edits` is what it did."""
    assert ["c.py", 4] not in errors_collect.collect(1)["cases"]["one__case"]["applied"]


def test_a_collected_record_carries_no_line_of_anybody_elses_source(collected: Path) -> None:
    """`evidence` is the only field that can hold a source excerpt."""
    text = json.dumps(errors_collect.collect(1))
    assert "SECRET" not in text
    assert "evidence" not in text
    assert "column" not in text


def test_a_checkout_with_two_run_folders_is_refused(
    collected: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    shutil.rmtree(collected / "work" / "round-1" / "one__case")
    write_work_tree(collected / "work" / "round-1", "one__case", "a" * 40, runs=2)
    with pytest.raises(SystemExit, match="expected one run folder, found 2"):
        errors_collect.collect(1)


def test_a_checkout_with_no_run_folder_is_refused(collected: Path) -> None:
    folder = collected / "work" / "round-1" / "one__case" / ".obelize" / "runs"
    for child in folder.iterdir():
        for leaf in child.iterdir():
            leaf.unlink()
        child.rmdir()
    with pytest.raises(SystemExit, match="expected one run folder, found 0"):
        errors_collect.collect(1)


def test_a_run_of_a_different_commit_is_refused(collected: Path) -> None:
    import shutil

    shutil.rmtree(collected / "work" / "round-1" / "one__case")
    write_work_tree(collected / "work" / "round-1", "one__case", "b" * 40)
    with pytest.raises(SystemExit, match="run folder git_sha is 'bbb"):
        errors_collect.collect(1)


def test_a_run_of_a_different_pack_is_refused(collected: Path) -> None:
    import shutil

    shutil.rmtree(collected / "work" / "round-1" / "one__case")
    write_work_tree(collected / "work" / "round-1", "one__case", "a" * 40, pack="q" * 64)
    with pytest.raises(SystemExit, match="run folder pack is 'qqq"):
        errors_collect.collect(1)


def test_a_missing_checkout_is_refused(collected: Path) -> None:
    import shutil

    shutil.rmtree(collected / "work" / "round-1" / "one__case")
    with pytest.raises(SystemExit, match="the work tree is gone"):
        errors_collect.collect(1)


def test_a_round_nobody_has_run_cannot_be_collected(collected: Path) -> None:
    (collected / "results" / "round-1" / "one__case.json").unlink()
    with pytest.raises(SystemExit, match="holds no result"):
        errors_collect.collect(1)


def test_collecting_writes_the_record_and_says_what_is_in_it(
    collected: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert errors_collect.main(["--round", "1"]) == 0
    written = json.loads((collected / "out" / "round-1.json").read_text(encoding="utf-8"))
    assert written["round"] == 1
    assert written["pack_sha256"] == ["p" * 64]
    assert "1 cases, 1 withheld rows" in capsys.readouterr().out


def test_the_round_number_defaults_to_the_one_the_case_file_declares(
    collected: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert errors_collect.main([]) == 0
    assert (collected / "out" / "round-1.json").is_file()
    capsys.readouterr()


def test_a_round_named_on_the_command_line_is_the_one_collected(
    collected: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (collected / "results" / "round-2").mkdir()
    (collected / "results" / "round-2" / "one__case.json").write_text(
        (collected / "results" / "round-1" / "one__case.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    write_work_tree(collected / "work" / "round-2", "one__case", "a" * 40)
    assert errors_collect.main(["--round", "2"]) == 0
    assert (collected / "out" / "round-2.json").is_file()
    assert not (collected / "out" / "round-1.json").exists()
    capsys.readouterr()
