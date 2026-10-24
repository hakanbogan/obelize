"""The `upgrade` dry-run measurement: its arithmetic, and a record read with its frame."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bench import upgrade_score
from platforms import BENCH

pytestmark = BENCH


def record(
    used: int,
    files: int = 0,
    *,
    rules: dict[str, int] | None = None,
    flagged: int = 0,
    written: int = 0,
    withheld: list[dict[str, Any]] | None = None,
    blocked: str | None = None,
    manifests: int = 0,
) -> dict[str, Any]:
    return {
        "full_name": "o/r",
        "sha": "0" * 40,
        "band": "size:<1000",
        "blocked": blocked,
        "manifests": manifests,
        "used": used,
        "rules": rules or {},
        "flagged": flagged,
        "written": written,
        "files": files,
        "withheld": withheld or [],
    }


def row(bail: str, symbol: str = "s") -> dict[str, Any]:
    return {"path": "app.py", "line": 1, "symbol": symbol, "bail": bail, "caused_by": None}


def synthetic() -> dict[str, Any]:
    return {
        "obelize_version": "0.0.0",
        "distribution": "lib",
        "from": "1.0.0",
        "to": "2.0.0",
        "pack": "lib/1-0-0-to-2-0-0",
        "pack_sha256": "ab" * 32,
        "synth_seconds": 12.5,
        "frame": "bench/upgrade/lib/sample.yaml",
        "upgrade": [
            record(0),
            record(4, 1, rules={"rename_member": 3}, flagged=1, written=4),
            record(
                5,
                0,
                rules={"rename_member": 1},
                flagged=3,
                withheld=[row("flag_only_surface", "lib.f"), row("repo_not_fully_migrated")],
            ),
            record(2, 0, blocked="legacy_version_unsupported", manifests=1, flagged=1),
            {"full_name": "o/e", "error": "RuntimeError: exit 2: /tmp/x went wrong"},
            {"full_name": "o/f", "error": "CalledProcessError: Command '['git', 'fetch']' failed"},
        ],
    }


FRAME = {"queried_at": "2026-10-24T00:00:00Z", "term": "t", "population": 4321}


def test_every_usage_is_counted_once_with_the_repositories_it_is_in() -> None:
    assert upgrade_score.usages(synthetic()["upgrade"][:4]) == [
        ("the pack flags it and never rewrites it", 5, 3),
        ("a rule rewrites it (`rename_member`)", 4, 2),
        (upgrade_score.OTHER, 2, 2),
    ]


def test_a_repository_with_no_usage_adds_no_row() -> None:
    assert upgrade_score.usages([record(0)]) == []


def test_the_section_reports_each_denominator() -> None:
    text = upgrade_score.render([(synthetic(), FRAME)])
    assert "### `lib` 1.0.0 to 2.0.0" in text
    assert "pack `lib/1-0-0-to-2-0-0` sha256 `abababababab`" in text
    assert "made from the two releases in 12.5 s" in text
    assert "(4,321 files in the index): 4 repositories planned, 2 errored, 3 with a usage." in text
    assert "| `none`: no usage found | 1 | 25.0% | 33.3% |" in text
    assert "| `complete`: a file written, nothing withheld | 1 | 25.0% | 33.3% |" in text
    assert "| `RuntimeError: exit 2` | 1 |" in text
    assert "| `CalledProcessError` | 1 |" in text
    assert "went wrong" not in text
    assert "| What became of a usage | Usages | Share of 11 | Repositories |" in text
    assert "| a rule rewrites it (`rename_member`) | 4 | 36.4% | 2 |" in text
    assert "4 of the 11 usages are in a file the dry run would write" in text
    assert "| `legacy_version_unsupported` | yes | 1 |" in text
    assert "| `repo_not_fully_migrated` | 1 | 1 | a consequence of another hold |" in text
    assert "| `lib.f` | `flag_only_surface` | 1 | 1 |" in text


def test_a_frame_with_nothing_planned_prints_dashes_not_a_division_by_zero() -> None:
    empty = synthetic()
    empty["upgrade"] = [{"full_name": "o/e", "error": "RuntimeError: exit 6: no index"}]
    text = upgrade_score.render([(empty, FRAME)])
    assert "0 repositories planned, 1 errored, 0 with a usage." in text
    assert "| What became of a usage | Usages | Share of 0 | Repositories |" in text
    assert "0 of the 0 usages" in text
    assert "Why a row was withheld" not in text
    assert "Why the pack stopped" not in text
    assert "Why a repository errored" in text


def test_a_clean_frame_has_no_error_table() -> None:
    clean = synthetic()
    clean["upgrade"] = [record(0)]
    assert "Why a repository errored" not in upgrade_score.render([(clean, FRAME)])


def test_a_record_is_read_with_the_frame_it_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "records").mkdir()
    (tmp_path / "records" / "lib.json").write_text(json.dumps(synthetic()), encoding="utf-8")
    (tmp_path / "bench" / "upgrade" / "lib").mkdir(parents=True)
    (tmp_path / "bench" / "upgrade" / "lib" / "sample.yaml").write_text(
        "queried_at: '2026-10-24T00:00:00Z'\nterm: t\npopulation: 4321\n", encoding="utf-8"
    )
    monkeypatch.setattr(upgrade_score, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(upgrade_score, "ROOT", tmp_path)
    [(loaded, frame)] = upgrade_score.load()
    assert loaded["pack"] == "lib/1-0-0-to-2-0-0"
    assert frame["population"] == 4321


def test_every_repository_of_the_frame_is_planned_once() -> None:
    """A retry of one repository must not leave a record that covers part of its frame."""
    for scored, frame in upgrade_score.load():
        drawn = {row["full_name"]: row for row in frame["repositories"]}
        assert [planned["full_name"] for planned in scored["upgrade"]] == list(drawn)
        for planned in scored["upgrade"]:
            assert drawn[planned["full_name"]]["sha"] == planned["sha"]
            assert drawn[planned["full_name"]]["band"] == planned["band"]
        assert (frame["from"], frame["to"]) == (scored["from"], scored["to"])


def test_without_check_the_block_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    assert upgrade_score.main([]) == 0
    assert capsys.readouterr().out == upgrade_score.render(upgrade_score.load()) + "\n"


def test_check_mode_passes_when_the_block_is_what_the_scorer_renders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    begin, end = upgrade_score.MARKERS
    current = tmp_path / "BENCHMARK_RESULTS.md"
    current.write_text(f"{begin}\n\n{upgrade_score.render(upgrade_score.load())}\n\n{end}\n")
    monkeypatch.setattr(upgrade_score, "DOCUMENT", current)
    assert upgrade_score.main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_a_stale_document_fails_the_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stale = tmp_path / "BENCHMARK_RESULTS.md"
    stale.write_text("\n".join([*upgrade_score.MARKERS]), encoding="utf-8")
    monkeypatch.setattr(upgrade_score, "DOCUMENT", stale)
    monkeypatch.setattr(upgrade_score, "load", lambda: [(synthetic(), FRAME)])
    assert upgrade_score.main(["--check"]) == 1
    assert "stale" in capsys.readouterr().out


def test_a_document_with_no_markers_is_an_error() -> None:
    with pytest.raises(SystemExit, match="no upgrade block"):
        upgrade_score.block("# Benchmark results\n")
