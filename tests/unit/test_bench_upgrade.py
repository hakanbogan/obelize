"""The `upgrade` dry-run measurement: its arithmetic, and a record read with its frame."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from bench import dryrun_score, upgrade_score
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


REPOSITORY_RULE = (
    "it writes a repository's plan only when nothing in it is left (`complete` above)."
)
FILE_RULE = (
    "it writes a file unless a place in it is left, and the pin follows the files written "
    "(`partial` and `complete` above)."
)


def test_a_record_with_no_unit_is_of_the_release_that_wrote_a_repository_whole() -> None:
    """A record of 0.9.0, which wrote a repository whole, names no unit; its sentence holds."""
    text = upgrade_score.render([(synthetic(), FRAME)])
    assert f"4 of the 11 usages are in a file the dry run would write: {REPOSITORY_RULE}" in text
    assert FILE_RULE not in text


def test_a_record_made_with_the_file_at_a_time_rule_says_what_that_rule_writes() -> None:
    made = {**synthetic(), "unit": "file"}
    made["upgrade"][2] = record(
        5, 2, rules={"rename_member": 1}, flagged=3, written=2, withheld=[row("flag_only_surface")]
    )
    text = upgrade_score.render([(made, FRAME)])
    assert f"6 of the 11 usages are in a file the dry run would write: {FILE_RULE}" in text
    assert REPOSITORY_RULE not in text
    assert "| `partial`: a file written, a row withheld | 1 | 25.0% | 33.3% |" in text
    assert "| `held`: usages found, no file written | 0 | 0.0% | 0.0% |" in text


def test_the_collector_writes_the_unit_a_record_is_scored_by() -> None:
    from bench import upgrade_collect

    source = Path(upgrade_collect.__file__).read_text(encoding="utf-8")
    assert '"unit": "file"' in source
    committed = [json.loads(path.read_text()) for path in upgrade_score.RECORDS.glob("*.json")]
    assert committed
    assert all(one["unit"] == "file" for one in committed)


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


def test_every_committed_record_names_the_frame_it_was_drawn_from() -> None:
    records = sorted(upgrade_score.RECORDS.glob("*.json"))
    assert records
    for path in records:
        frame = upgrade_score.ROOT / json.loads(path.read_text(encoding="utf-8"))["frame"]
        assert frame.is_file(), path.name
        assert frame.parent.name == path.stem


def test_every_frame_has_a_record() -> None:
    frames = {
        path.parent.name for path in (upgrade_score.ROOT / "bench" / "upgrade").glob("*/*.yaml")
    }
    assert frames == {path.stem for path in upgrade_score.RECORDS.glob("*.json")}


def test_the_published_block_is_what_the_scorer_renders_today() -> None:
    published = upgrade_score.block(upgrade_score.DOCUMENT.read_text(encoding="utf-8"))
    assert published == upgrade_score.render(upgrade_score.load())


# The bail of a place the pack only flags, as `bench/upgrade_collect.py` counts it.
FLAGGED = "flag_only_surface"


def measured() -> dict[str, Any]:
    """The sums the pages quote, taken from the records."""
    loaded = upgrade_score.load()
    rows = [row for record, _ in loaded for row in record["upgrade"] if "error" not in row]
    tiers = Counter(dryrun_score.tier(row) for row in rows)
    held = [row for row in rows if dryrun_score.tier(row) == "held"]
    kinds = {kind for row in rows for kind in row["rules"]}
    seconds = [record["synth_seconds"] for record, _ in loaded]
    return {
        "planned": len(rows),
        "errored": sum(len(record["upgrade"]) for record, _ in loaded) - len(rows),
        "files": sum(row["files"] for row in rows),
        "writing": [row for row in rows if row["files"]],
        "tiers": tiers,
        "used": sum(row["used"] for row in rows),
        "rules": sum(sum(row["rules"].values()) for row in rows),
        "kinds": kinds,
        "flagged": sum(row["flagged"] for row in rows),
        "inwritten": sum(row["written"] for row in rows if row["files"]),
        "legacy": sum(row["blocked"] == "legacy_version_unsupported" for row in rows),
        "runtime": sum(row["blocked"] == "runtime_unsupported" for row in rows),
        "held_flagged": sum(
            any(held_row["bail"] == FLAGGED for held_row in row["withheld"]) for row in held
        ),
        "held_rows": held,
        "held_no_rule": sum(not any(row["rules"].values()) for row in held),
        "seconds": f"{round(min(seconds))} to {round(max(seconds))} s",
    }


def says(page: str, sentence: str) -> bool:
    """Whether the page prints `sentence`, wherever its lines wrap."""
    text = (upgrade_score.ROOT / page).read_text(encoding="utf-8")
    return " ".join(sentence.split()) in " ".join(text.split())


def test_the_measurement_wrote_a_file_for_five_pydantic_repositories_of_the_eighty() -> None:
    sums = measured()
    tiers = sums["tiers"]
    assert (sums["planned"], sums["errored"]) == (80, 0)
    assert (tiers["partial"], tiers["complete"]) == (5, 0)
    assert len(sums["writing"]) == 5
    assert sums["kinds"] == {"rename_member"}
    for record, _ in upgrade_score.load():
        in_pydantic = record["distribution"] == "pydantic"
        assert any(row["files"] for row in record["upgrade"]) == in_pydantic
        assert any(row["rules"] for row in record["upgrade"]) == in_pydantic


def test_the_pages_state_the_totals_of_the_records() -> None:
    sums = measured()
    tiers = sums["tiers"]
    written = tiers["partial"] + tiers["complete"]
    outcome = (
        f"writes a file for {written} and none for the other {sums['planned'] - written}: "
        f"{tiers['blocked']} stop before planning, {tiers['held']} are held and {tiers['none']} "
        "have no usage of a name the pack lists"
    )
    usages = (
        f"{sums['used']} usages: {sums['rules']} are places a rule would rewrite (all in pydantic, "
        f"`rename_member`), the pack only flags {sums['flagged']} and "
        f"{sums['used'] - sums['rules'] - sums['flagged']} are held for a cause of its own, and "
        f"{sums['inwritten']} are in a file the dry run would write"
    )
    mostly = (
        f"{sums['flagged']} of the {sums['used']} usages "
        f"({100 * sums['flagged'] / sums['used']:.1f}%) are places"
    )
    for page in (
        "README.md",
        "CHANGELOG.md",
        "docs/BENCHMARK_RESULTS.md",
        "docs/KNOWN_ISSUES.md",
        "docs/PRODUCT.md",
        "docs/ROADMAP.md",
        "docs/UPGRADING.md",
    ):
        assert says(page, outcome), page
    for page in (
        "README.md",
        "CHANGELOG.md",
        "docs/BENCHMARK_RESULTS.md",
        "docs/KNOWN_ISSUES.md",
        "docs/ROADMAP.md",
        "docs/UPGRADING.md",
    ):
        assert says(page, usages), page
    for page in (
        "README.md",
        "CHANGELOG.md",
        "docs/BENCHMARK_RESULTS.md",
        "docs/KNOWN_ISSUES.md",
        "docs/ROADMAP.md",
        "docs/UPGRADING.md",
    ):
        assert says(page, mostly), page


def test_the_pages_state_why_the_repositories_stopped_and_were_held() -> None:
    sums = measured()
    stopped = sums["tiers"]["blocked"]
    held = sums["tiers"]["held"]
    for page in ("docs/BENCHMARK_RESULTS.md", "docs/UPGRADING.md"):
        assert says(
            page,
            f"Of the {stopped} that stop, {sums['legacy']} stop on a manifest that declares the "
            f"library in a way the pack does not take (`legacy_version_unsupported`",
        ), page
        assert says(page, f"{sums['runtime']} on a declared Python that the new release does"), page
    unread = held - sums["held_flagged"]
    assert all(
        any(held_row["bail"] == "input_does_not_parse" for held_row in row["withheld"])
        for row in sums["held_rows"]
        if not any(held_row["bail"] == FLAGGED for held_row in row["withheld"])
    )
    for page, lead in (
        ("docs/UPGRADING.md", f"Each of the {held} that are held"),
        ("docs/BENCHMARK_RESULTS.md", f"Of the {held} that are held, each"),
    ):
        assert says(
            page,
            f"{lead} has a place the pack cannot write: {sums['held_flagged']} have one it only "
            f"flags, and {unread} have a file the scan cannot parse",
        ), page
    assert says("docs/KNOWN_ISSUES.md", f"{sums['legacy']} of the {sums['planned']} stop on this")
    assert says("CHANGELOG.md", f"{sums['held_flagged']} of the {held} held")
    assert says(
        "docs/KNOWN_ISSUES.md",
        f"{sums['held_no_rule']} of the {held} held repositories",
    )
    assert says("docs/UPGRADING.md", f"a pack from two releases in {sums['seconds']} for four")
    assert says(
        "docs/BENCHMARK_RESULTS.md", f"A pack from two releases was made in {sums['seconds']} for"
    )
