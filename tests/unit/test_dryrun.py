"""The `fix` dry-run measurement: its tiers and arithmetic, and the committed records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bench import dryrun_score
from platforms import BENCH

ROOT = Path(__file__).resolve().parents[2]

pytestmark = BENCH


def row(bail: str, symbol: str | None = "s", caused_by: list[str] | None = None) -> dict[str, Any]:
    return {"path": "app.py", "line": 1, "symbol": symbol, "bail": bail, "caused_by": caused_by}


def record(
    used: int,
    files: int,
    *withheld: dict[str, Any],
    blocked: str | None = None,
    manifests: int = 0,
) -> dict[str, Any]:
    return {
        "full_name": "o/r",
        "sha": "0" * 40,
        "band": "size:<1000",
        "blocked": blocked,
        "used": used,
        "manifests": manifests,
        "files": files,
        "withheld": withheld,
    }


@pytest.mark.parametrize(
    ("planned", "expected"),
    [
        (
            record(3, 0, blocked="legacy_version_unsupported"),
            "blocked",
        ),
        (record(0, 0), "none"),
        (record(0, 0, row("manifest_code_mismatch"), manifests=1), "none"),
        (record(2, 0, row("flag_only_surface")), "held"),
        (record(3, 1, row("repo_not_fully_migrated")), "partial"),
        (record(2, 2), "complete"),
    ],
)
def test_a_repository_lands_in_exactly_one_tier(planned: dict[str, Any], expected: str) -> None:
    assert dryrun_score.tier(planned) == expected
    assert expected in dict(dryrun_score.TIERS)


def test_a_bail_counts_its_rows_and_each_repository_once() -> None:
    held = [
        record(3, 0, row("a"), row("a"), row("b")),
        record(1, 1, row("a")),
    ]
    assert dryrun_score.withheld(held) == [("a", 3, 2), ("b", 1, 1)]


def test_a_repository_with_nothing_withheld_has_no_bail_to_count() -> None:
    assert dryrun_score.withheld([record(1, 1)]) == []


def test_a_cause_is_a_symbol_and_a_bail_and_leaves_out_the_derived_rows() -> None:
    held = [
        record(3, 0, row("a", "x"), row("a", "x"), row("a", "y"), row("repo_not_fully_migrated")),
        record(1, 1, row("a", "x"), row("b", "x"), row("parse_error", None)),
    ]
    assert dryrun_score.causes(held) == [
        ("x", "a", 3, 2),
        ("(none)", "parse_error", 1, 1),
        ("x", "b", 1, 1),
        ("y", "a", 1, 1),
    ]


def synthetic() -> dict[str, Any]:
    return {
        "pack": "p/q",
        "obelize_version": "0.0.0",
        "pack_sha256": "ab" * 32,
        "frame": "bench/gate1/p__q/sample.yaml",
        "dry_run": [
            record(0, 0),
            record(2, 0, row("flag_only_surface"), row("repo_not_fully_migrated")),
            record(1, 1),
            record(1, 0, blocked="legacy_version_unsupported"),
            record(1, 0, blocked="legacy_version_unsupported", manifests=1),
            {"full_name": "o/e", "error": "RuntimeError: exit 1"},
        ],
    }


FRAME = {"queried_at": "2026-10-13T00:00:00Z", "term": "t", "population": 1234}


def test_the_section_reports_each_tier_beside_both_denominators() -> None:
    text = dryrun_score.render([(synthetic(), FRAME)])
    assert "### `p/q`" in text
    assert "5 repositories planned, 1 errored" in text
    assert "1,234 files in the index" in text
    assert "| `none`: no usage found | 1 | 20.0% | 33.3% |" in text
    assert (
        "| `blocked`: the pack stops before it plans, for the reason below | 2 | 40.0% | -- |"
        in text
    )
    assert "| `legacy_version_unsupported` | no | 1 |" in text
    assert "| `legacy_version_unsupported` | yes | 1 |" in text
    assert "| `repo_not_fully_migrated` | 1 | 1 | a consequence of another hold |" in text
    assert "| `flag_only_surface` | 1 | 1 |  |" in text
    assert "| `s` | `flag_only_surface` | 1 | 1 |" in text


def test_a_frame_with_nothing_planned_prints_dashes_not_a_division_by_zero() -> None:
    empty = synthetic()
    empty["dry_run"] = [{"full_name": "o/e", "error": "RuntimeError: exit 1"}]
    text = dryrun_score.render([(empty, FRAME)])
    assert "0 repositories planned, 1 errored" in text
    assert "| 0 | -- | -- |" in text
    assert "Why a row was withheld" not in text
    assert "symbols that hold back" not in text
    assert "Why the pack stopped" not in text


def test_the_measurement_was_run_against_the_pack_that_ships_today() -> None:
    """A pack edit moves what a dry run plans, so the page has to be re-measured."""
    from obelize.packs import loader

    for scored, _ in dryrun_score.load():
        assert scored["pack_sha256"] == loader.load(scored["pack"]).sha256


def test_every_repository_of_the_frame_is_planned_once() -> None:
    """A retry of one repository must not leave a record that covers part of its frame."""
    for scored, frame in dryrun_score.load():
        drawn = {row["full_name"]: row for row in frame["repositories"]}
        assert [planned["full_name"] for planned in scored["dry_run"]] == list(drawn)
        for planned in scored["dry_run"]:
            assert drawn[planned["full_name"]]["sha"] == planned["sha"]
            assert drawn[planned["full_name"]]["band"] == planned["band"]


def test_the_published_block_is_what_the_scorer_renders_today() -> None:
    published = dryrun_score.block(dryrun_score.DOCUMENT.read_text(encoding="utf-8"))
    assert published == dryrun_score.render(dryrun_score.load())


def test_check_mode_passes_and_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    assert dryrun_score.main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_without_check_the_block_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    assert dryrun_score.main([]) == 0
    assert "Why a row was withheld" in capsys.readouterr().out


def test_a_stale_document_fails_the_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stale = tmp_path / "BENCHMARK_RESULTS.md"
    stale.write_text("\n".join([*dryrun_score.MARKERS]), encoding="utf-8")
    monkeypatch.setattr(dryrun_score, "DOCUMENT", stale)
    assert dryrun_score.main(["--check"]) == 1
    assert "stale" in capsys.readouterr().out


def test_a_document_with_no_markers_is_an_error() -> None:
    with pytest.raises(SystemExit, match="no dryrun block"):
        dryrun_score.block("# Benchmark results\n")
