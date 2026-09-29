"""Gate 1: scorer arithmetic, committed inputs against `docs/BENCHMARK.md`, and staleness.

The published number decides Phase 2's scope, so it must be recomputable.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from obelize.models import CONFIDENCE_REASONS, FINDING_KINDS, WITHHELD
from platforms import BENCH

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import gate1_score  # noqa: E402 -- the path insert above is what makes this importable

pytestmark = BENCH


def finding(**overrides: Any) -> dict[str, Any]:
    """One finding, with only the fields the scorer reads."""
    row = {
        "path": "app.py",
        "line": 1,
        "kind": "call",
        "symbol": "genai.configure",
        "scan_status": "eligible",
        "confidence_reason": "alias_resolved",
    }
    row.update(overrides)
    return row


def test_rows_keeps_a_duplicate_and_drops_the_kinds_not_being_measured() -> None:
    """Two identical rows are two rows: a set would score the second as missing."""
    counted = gate1_score.rows(
        [finding(), finding(), finding(kind="text_mention")],
        gate1_score.ACTIONABLE_KINDS,
    )
    assert counted == Counter({gate1_score.Row("app.py", 1, "call", "genai.configure"): 2})


def test_a_finding_with_no_symbol_compares_as_the_empty_string() -> None:
    """`parse_error` carries none, and `None` is not a symbol two keys can share."""
    counted = gate1_score.rows([finding(symbol=None, kind="import")], gate1_score.ACTIONABLE_KINDS)
    assert next(iter(counted)).symbol == ""


def test_the_right_line_with_the_wrong_symbol_is_a_miss_and_a_false_positive() -> None:
    """Strict: `obelize scan` prints the symbol, so a wrong one misleads about the user's file."""
    key = Counter({gate1_score.Row("app.py", 1, "call", "genai.configure"): 1})
    found = Counter({gate1_score.Row("app.py", 1, "call", "genai.configur"): 1})
    accuracy = gate1_score.compare(key, found)
    assert (accuracy.true_positive, accuracy.false_positive, accuracy.missed) == (0, 1, 1)


def test_precision_and_recall_over_a_partial_match() -> None:
    key = Counter(
        {
            gate1_score.Row("a.py", 1, "import", "google.generativeai"): 1,
            gate1_score.Row("a.py", 9, "call", "genai.configure"): 1,
        }
    )
    found = Counter(
        {
            gate1_score.Row("a.py", 1, "import", "google.generativeai"): 1,
            gate1_score.Row("b.py", 4, "call", "genai.configure"): 1,
        }
    )
    accuracy = gate1_score.compare(key, found)
    assert (accuracy.true_positive, accuracy.false_positive, accuracy.missed) == (1, 1, 1)
    assert accuracy.precision == 0.5
    assert accuracy.recall == 0.5


def test_finding_nothing_is_not_precision_one() -> None:
    """0/0 is not a score; `100.0%` for a scanner that reported nothing would flatter it."""
    accuracy = gate1_score.compare(Counter({gate1_score.Row("a.py", 1, "call", "x"): 1}), Counter())
    assert accuracy.precision is None
    assert accuracy.recall == 0.0


def test_an_empty_key_has_no_recall() -> None:
    assert gate1_score.compare(Counter(), Counter()).recall is None


def test_one_withheld_finding_disqualifies_the_whole_file() -> None:
    """ADR-010 F-1: a file with one bail is left as it was, so its eligible import stays too."""
    assert (
        gate1_score.zero_bail_files(
            [
                finding(kind="import", symbol="google.generativeai"),
                finding(line=9, scan_status="needs_review"),
            ]
        )
        == []
    )


def test_a_file_whose_only_eligible_row_is_a_mention_does_not_count() -> None:
    """A `text_mention` is eligible but nothing a codemod can act on."""
    assert gate1_score.zero_bail_files([finding(kind="text_mention", symbol="genai")]) == []


def test_a_not_a_usage_row_withholds_nothing() -> None:
    assert gate1_score.zero_bail_files(
        [
            finding(kind="import", symbol="google.generativeai"),
            finding(path="test_app.py", kind="call", scan_status="not_a_usage"),
        ]
    ) == ["app.py"]


def test_the_files_come_back_sorted_and_de_duplicated() -> None:
    """Ten reversed paths: an unsorted set of two passes half the time; of ten, 1 in 10!."""
    paths = [f"{name}.py" for name in "zyxwvutsrq"]
    rows = [finding(path=path) for path in paths] + [finding(path="q.py", line=2)]
    assert gate1_score.zero_bail_files(rows) == sorted(paths)


def test_resolution_counts_only_the_reasons_that_are_a_usage() -> None:
    resolved, unresolved = gate1_score.resolution(
        [
            finding(confidence_reason="alias_resolved"),
            finding(confidence_reason="receiver_unresolved"),
            finding(confidence_reason="string_or_comment_mention"),
            finding(confidence_reason="manifest_dependency"),
        ]
    )
    assert (resolved, unresolved) == (1, 1)


def test_the_two_reason_sets_partition_the_usages_and_nothing_else() -> None:
    """They stand in for gate 1's "cannot be resolved statically"; a leak redefines the rate."""
    assert gate1_score.RESOLVED_REASONS.isdisjoint(gate1_score.UNRESOLVED_REASONS)
    both = gate1_score.RESOLVED_REASONS | gate1_score.UNRESOLVED_REASONS
    assert both <= CONFIDENCE_REASONS
    assert CONFIDENCE_REASONS - both == {
        "string_or_comment_mention",
        "mock_patch_target",
        "manifest_dependency",
        "parse_error",
    }


def test_the_scorer_agrees_with_the_package_about_what_withholding_is() -> None:
    """The scorer copies these so a package change shows up here, not as a silent re-grade."""
    assert gate1_score.WITHHELD_STATUSES == WITHHELD
    assert gate1_score.ACTIONABLE_KINDS < FINDING_KINDS
    assert gate1_score.ACTIONABLE_KINDS.isdisjoint(gate1_score.OTHER_KINDS)
    assert gate1_score.ACTIONABLE_KINDS | gate1_score.OTHER_KINDS == FINDING_KINDS


def _synthetic() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """One of two fetches failed: it counts in its band's `Errored` column and in no rate."""
    sample = {
        "queried_at": "2026-09-18T00:00:00Z",
        "term": "generativeai",
        "bands": [{"band": "size:<1000", "population": 10, "allocated": 2, "drawn": 2}],
        "population": 10,
        "excluded_owners": ["eli64s"],
        "repositories": [
            {"full_name": "a/one", "owner": "a", "sha": "0" * 40, "band": "size:<1000"},
            {"full_name": "b/two", "owner": "b", "sha": "1" * 40, "band": "size:<1000"},
        ],
    }
    scanned = {
        "obelize_version": "0.0.0",
        "pack": "p",
        "pack_sha256": "f" * 64,
        "spec_sha256": "e" * 64,
        "python": "3.12.0",
        "machine": "arm64",
        "os": "Darwin",
        "scanned": [
            {
                "full_name": "a/one",
                "sha": "0" * 40,
                "band": "size:<1000",
                "counts": {"files_selected": 3, "files_parsed": 1},
                "runtime": {"declared": ">=3.9", "path": "pyproject.toml", "blocked": True},
                "findings": [
                    finding(kind="import", symbol="google.generativeai"),
                    finding(path="requirements.txt", line=2, kind="manifest", symbol="x"),
                ],
            },
            {
                "full_name": "b/two",
                "sha": "1" * 40,
                "band": "size:<1000",
                "error": "CalledProcessError: fetch failed",
            },
        ],
    }
    labels = [
        {
            "repository": "a/one",
            "url": "https://example.invalid/a/one",
            "files_read": ["app.py"],
            "call_sites": [
                {"path": "app.py", "line": 1, "kind": "call", "symbol": "genai.configure"}
            ],
            "expected_other": [],
            "must_not_report": [{"path": "app.py", "line": 1, "why": "forbidden on purpose"}],
        }
    ]
    return sample, scanned, labels


def test_an_errored_repository_is_counted_and_never_averaged_in() -> None:
    sample, scanned, labels = _synthetic()
    assert gate1_score.outcomes(scanned) == (1, 0, 0)
    block = gate1_score.render(sample, scanned, labels)
    assert "1 scanned" in block
    assert "| `size:<1000` | 10 | 1 | 1 | 1 | 100.0% |" in block


def test_a_blocked_declaration_is_named_in_the_table_and_in_the_total() -> None:
    """Nothing committed is blocked (78 of eighty declare no floor); only this tests the mark."""
    sample, scanned, labels = _synthetic()
    block = gate1_score.render(sample, scanned, labels)
    assert "| `>=3.9` | 1 | **blocked** |" in block
    assert "| **Blocked** | **1** | |" in block


def test_a_repository_that_declares_nothing_is_counted_apart_from_one_that_does() -> None:
    """The two ways `blocked` is false stay apart: a floor admitting 3.10, and no floor."""
    _, scanned, _ = _synthetic()
    assert gate1_score.declarations(scanned) == Counter({">=3.9": 1})
    scanned["scanned"][0]["runtime"] = {"declared": None, "blocked": False}
    assert gate1_score.declarations(scanned) == Counter({"(none declared)": 1})


def test_a_forbidden_position_that_was_reported_is_named() -> None:
    """No committed key trips `must_not_report`, so the synthetic one does."""
    _, scanned, labels = _synthetic()
    assert gate1_score.violations(scanned, labels) == ["a/one app.py:1"]


def test_a_repository_whose_every_file_bails_is_counted_as_none() -> None:
    _, scanned, _ = _synthetic()
    scanned["scanned"][0]["findings"][0]["scan_status"] = "needs_review"
    assert gate1_score.outcomes(scanned) == (0, 0, 1)


def test_a_repository_with_one_good_file_and_one_bad_is_partial() -> None:
    _, scanned, _ = _synthetic()
    scanned["scanned"][0]["findings"].append(finding(path="other.py", scan_status="unsupported"))
    assert gate1_score.outcomes(scanned) == (0, 1, 0)


@pytest.fixture(scope="module")
def inputs() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    return gate1_score.load()


def test_the_frame_is_large_enough_and_owner_disjoint(
    inputs: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    """Sixty is the roadmap's floor; `docs/BENCHMARK.md` forbids two cases from one owner."""
    sample, _, _ = inputs
    repositories = sample["repositories"]
    assert len(repositories) >= 60
    owners = [row["owner"] for row in repositories]
    assert len(set(owners)) == len(owners)
    assert not set(owners) & set(sample["excluded_owners"])
    for row in repositories:
        assert len(row["sha"]) == 40
        assert row["license"]


def test_every_scanned_repository_is_one_the_frame_names(
    inputs: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    sample, scanned, _ = inputs
    frame = {row["full_name"]: row["sha"] for row in sample["repositories"]}
    assert {record["full_name"] for record in scanned["scanned"]} == set(frame)
    for record in scanned["scanned"]:
        assert record["sha"] == frame[record["full_name"]]


def test_there_are_five_answer_keys_and_each_one_was_written_against_the_pinned_sha(
    inputs: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    """Five is gate 1's number; the SHA check stops grading a key against another commit."""
    sample, _, labels = inputs
    frame = {row["full_name"]: row for row in sample["repositories"]}
    assert len(labels) == 5
    for label in labels:
        assert label["repository"] in frame
        assert label["sha"] == frame[label["repository"]]["sha"]
        assert label["files_read"]
        assert label["labeller"]
        assert label["labelled_at"]


def test_every_labelled_call_site_is_an_actionable_row(
    inputs: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    _, _, labels = inputs
    for label in labels:
        for site in label["call_sites"]:
            assert site["kind"] in gate1_score.ACTIONABLE_KINDS
            assert site["line"] >= 1
            assert site["symbol"]
        for row in label["expected_other"]:
            assert row["kind"] in FINDING_KINDS - gate1_score.ACTIONABLE_KINDS
            assert row["line"] >= 1
            assert row["symbol"]
        for row in label["must_not_report"]:
            assert row["line"] >= 1
            assert row["why"]


def test_the_answer_keys_do_not_share_an_owner_with_each_other_or_the_corpus(
    inputs: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    sample, _, labels = inputs
    owners = [label["repository"].split("/")[0] for label in labels]
    assert len(set(owners)) == len(owners)
    assert not set(owners) & set(sample["excluded_owners"])


def test_the_measurement_was_run_against_the_pack_that_ships_today(
    inputs: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    """The shipped pack must still match the measurement, by `spec_sha256`, not `pack_sha256`.

    A rewrite-only edit (parameters, wrap width) moves the file hash but no finding: `scan/*` and
    `impact/*` never see it (ADR-026 D8). `pack_sha256` still names the document measured.
    """
    from obelize.cli import DEFAULT_PACK
    from obelize.packs import loader

    _, scanned, _ = inputs
    assert scanned["pack"] == DEFAULT_PACK
    shipped = loader.spec_digest(loader.to_scan_spec(loader.load(DEFAULT_PACK)))
    assert scanned["spec_sha256"] == shipped


def test_the_published_block_is_what_the_scorer_renders_today(
    inputs: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
) -> None:
    published = gate1_score.block(gate1_score.DOCUMENT.read_text(encoding="utf-8"))
    assert published == gate1_score.render(*inputs)


def test_check_mode_passes_and_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    assert gate1_score.main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_without_check_the_block_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    assert gate1_score.main([]) == 0
    assert "Precision and recall" in capsys.readouterr().out


def test_a_stale_document_fails_the_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stale = tmp_path / "BENCHMARK_RESULTS.md"
    stale.write_text("\n".join([*gate1_score.MARKERS]), encoding="utf-8")
    monkeypatch.setattr(gate1_score, "DOCUMENT", stale)
    assert gate1_score.main(["--check"]) == 1
    assert "stale" in capsys.readouterr().out


def test_a_document_with_no_markers_is_an_error() -> None:
    with pytest.raises(SystemExit, match="no gate1 block"):
        gate1_score.block("# Benchmark results\n")
