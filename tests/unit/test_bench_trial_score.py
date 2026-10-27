"""The trial measurement's scorer: a synthetic record renders to the expected block, the quoted
sums are recomputed from the records, and a stale or missing block fails the check."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import trialrecords as records

from bench import trial_box, trial_score
from platforms import BENCH

pytestmark = BENCH

EXPECTED = """### `lib` 1.0.0 to 2.0.0

obelize 0.10.0 from commit `cccccccccc` (wheel sha256 `bbbbbbbbbbbb`), image `dddddddddddd`, Docker 29.8.2, uv 0.12.15 (aarch64-unknown-linux-gnu), Linux aarch64, run on 2026-10-29T08:00:00Z. Each container had 2 GiB of memory, 2 CPUs, 1,024 processes, 8 GiB of disk and 90 minutes. The self-test passed at 2026-10-29T07:59:00Z after 22 attempts to get out or to be refused. The proxy carried 410 connections to files.pythonhosted.org:443 and 90 connections to pypi.org:443 and refused 2.

5 repositories were tried.

| Outcome | Repositories | Share of tried |
|---|---:|---:|
| `pass`: the tests that passed before pass, the whole move written | 1 | 20.0% |
| `pass`: the tests pass, and places were left for a person (`partial`) | 1 | 20.0% |
| `fail`, `tests_broke`: a test that passed before the move broke | 1 | 20.0% |
| `inconclusive`, `no_tests`: the repository has no tests the trial could run | 1 | 20.0% |
| `error`, `environment`: the dependencies could not be installed | 1 | 20.0% |
| `timeout`: the container ran past its time limit | 0 | 0.0% |

62 tests that passed before were compared in 3 trials; 2 broke and 1 failed once and passed again. The 2 passing trials wrote 5 files and left 1 files and 3 places for a person. A repository took 40 s at the median and 300 s at the longest, 413.5 s in all.

### What these numbers are not

These 5 repositories are the ones of the 20 drawn whose dry run writes a file (a plan written by the file rule), so a repository the plan could not write is not here. The frames were drawn by code search of public repositories that import the old API, which favours small single-purpose projects. The trial installs what the repository's own recipe names and runs pytest, since no test command is known; a repository with another way of testing is `inconclusive`. A `pass` means the tests that existed and passed before still pass: it says nothing about code no test reaches, and 1 of the passes left places for a person. The box is a Linux container (aarch64) with a fixed uv, Pythons 3.9, 3.12, 3.13 (one chosen per repository by its `requires-python`) and the packages the index held on the day, so a repository that needs a service, a secret, a system library the image lacks or more memory, time or disk than the limits above ends as `error`, `inconclusive` or `timeout`, and the passes lean towards self-contained suites."""  # noqa: E501 - the block is one line per paragraph


def test_a_synthetic_record_renders_to_the_expected_block() -> None:
    assert trial_score.render([(records.record(), records.FRAME)]) == EXPECTED


def test_with_no_record_there_is_nothing_to_render() -> None:
    assert trial_score.render([]) == ""


def test_two_frames_each_have_a_section_and_the_frames_have_one_together() -> None:
    other = records.record(
        [records.row("pass", written=1, compared=3), records.row("timeout", "wall_clock")],
        distribution="other",
        **{"from": "3.0", "to": "4.0"},
        proxy=None,
        obelize_commit=None,
    )
    text = trial_score.render([(records.record(), records.FRAME), (other, records.FRAME)])
    assert [line for line in text.splitlines() if line.startswith("### ")] == [
        "### `lib` 1.0.0 to 2.0.0",
        "### `other` 3.0 to 4.0",
        "### All frames",
        "### What these numbers are not",
    ]
    assert "obelize 0.10.0 from a wheel built elsewhere" in text
    assert "The proxy carried nothing and refused 0." in text
    assert "7 repositories were tried." in text
    assert "| `timeout`, `wall_clock`: the container ran past its time limit | 1 | 14.3% |" in text
    assert "These 7 repositories are the ones of the 40 drawn" in text


def counts(text: str) -> dict[str, int]:
    return {
        match[1]: int(match[2])
        for match in re.finditer(r"^\| (.+?) \| (\d+) \| [\d.]+% \|$", text, re.MULTILINE)
    }


def test_the_quoted_sums_are_the_records_own_arithmetic() -> None:
    rows = [
        records.row("pass", compared=10, written=4, held=0, seconds=3.0),
        records.row("pass", compared=5, written=2, held=3, partial=True, seconds=9.0, flaky=1),
        records.row("fail", "tests_broke", compared=7, broken_count=2, seconds=5.0),
        records.row("fail", "tests_broke", compared=1, broken_count=1, seconds=1.0),
        records.row("inconclusive", "no_junit", seconds=2.0),
        records.row("inconclusive", "no_junit", seconds=2.0),
        records.row("inconclusive", "timeout", seconds=2.0),
        records.row("error", "oom", seconds=7.0),
    ]
    text = trial_score.render([(records.record(rows), records.FRAME)])
    assert "8 repositories were tried." in text
    assert (
        "23 tests that passed before were compared in 4 trials; 3 broke and 1 failed once and "
        "passed again. The 2 passing trials wrote 6 files and left 3 files and 0 places for a "
        "person. A repository took 2.5 s at the median and 9 s at the longest, 31 s in all."
    ) in text
    shown = counts(text)
    assert shown["`pass`: the tests that passed before pass, the whole move written"] == 1
    assert shown["`pass`: the tests pass, and places were left for a person (`partial`)"] == 1
    assert shown["`fail`, `tests_broke`: a test that passed before the move broke"] == 2
    assert shown["`inconclusive`, `no_junit`: the tests produced no result the trial can read"] == 2
    assert shown["`inconclusive`, `timeout`: the tests did not finish in time"] == 1
    assert shown["`error`, `oom`: the container ran out of memory before a verdict"] == 1
    assert shown["`timeout`: the container ran past its time limit"] == 0
    assert sum(shown.values()) == 8
    assert text.index("`no_junit`") < text.index("`inconclusive`, `timeout`")


def test_a_status_nobody_had_still_has_its_row() -> None:
    text = trial_score.render([(records.record([records.row("pass")]), records.FRAME)])
    assert "| `fail`: a test that passed before the move broke | 0 | 0.0% |" in text
    assert "| `inconclusive`: the tests could not judge the move | 0 | 0.0% |" in text
    assert "| `error`: the trial did not reach a verdict | 0 | 0.0% |" in text


def test_every_reason_a_record_may_hold_is_explained() -> None:
    for status, reasons in trial_box.REASONS.items():
        for reason in reasons:
            if status != "pass":
                assert (status, reason) in trial_score.MEANING
    assert set(trial_score.NONE) == {"fail", "inconclusive", "error", "timeout"}


# The document.

SKELETON = (
    "# Benchmark results\n\n"
    "| [Upgrade dry run](#upgrade-dry-run) | `a` | `b` |\n"
    "| [Round 1](#round-1) | `c` | `d` |\n\n"
    "## Upgrade dry run\n\ntext\n\n## Round 1\n\nmore\n"
)


def test_a_section_is_put_before_round_1_with_its_row_in_the_table() -> None:
    generated = trial_score.render([(records.record(), records.FRAME)])
    text = trial_score.written(SKELETON, generated)
    begin, end = trial_score.MARKERS
    assert text.index("| [Upgrade trial](#upgrade-trial)") < text.index("| [Round 1]")
    assert (
        text.index("## Upgrade dry run") < text.index("## Upgrade trial") < text.index("## Round 1")
    )
    section = f"{trial_score.HEADING}\n\n{trial_score.INTRO}\n\n{begin}\n\n{generated}\n\n{end}"
    assert f"{section}\n\n## Round 1" in text
    assert trial_score.block(text) == generated
    assert trial_score.written(text, generated) == text


def test_a_block_that_is_there_is_replaced_in_place() -> None:
    first = trial_score.render([(records.record(), records.FRAME)])
    text = trial_score.written(SKELETON, first)
    changed = trial_score.render([(records.record([records.row("pass")]), records.FRAME)])
    again = trial_score.written(text, changed)
    assert trial_score.block(again) == changed
    assert again.count(trial_score.HEADING) == 1
    assert again.endswith("## Round 1\n\nmore\n")


def test_a_document_without_the_markers_has_no_block() -> None:
    assert trial_score.block(SKELETON) is None
    assert trial_score.block(f"{trial_score.MARKERS[0]}\nonly the start") is None


def put(path: Path, rows: list[dict[str, Any]] | None = None, **kept: Any) -> Path:
    """A record under `path`'s records folder, with the frame it names."""
    (path / "records").mkdir(exist_ok=True)
    (path / "bench" / "upgrade" / "lib").mkdir(parents=True, exist_ok=True)
    (path / "bench" / "upgrade" / "lib" / "sample.yaml").write_text(
        "queried_at: '2026-10-24T00:00:00Z'\nterm: t\npopulation: 5\n"
        "repositories:\n- full_name: o/r\n",
        encoding="utf-8",
    )
    target = path / "records" / "lib.json"
    target.write_text(json.dumps(records.record(rows, **kept)), encoding="utf-8")
    return target


@pytest.fixture
def folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(trial_score, "RECORDS", tmp_path / "records")
    monkeypatch.setattr(trial_score, "ROOT", tmp_path)
    monkeypatch.setattr(trial_score, "DOCUMENT", tmp_path / "BENCHMARK_RESULTS.md")
    (tmp_path / "records").mkdir()
    return tmp_path


def test_a_record_is_read_with_the_frame_it_names(folder: Path) -> None:
    put(folder)
    [(loaded, frame)] = trial_score.load()
    assert loaded["distribution"] == "lib"
    assert frame["population"] == 5


def test_a_record_that_is_not_one_stops_the_run(folder: Path) -> None:
    put(folder, selftest={"passed": False, "attempts": {}, "at": "x"})
    with pytest.raises(SystemExit, match=r"lib\.json is not a record: the self-test did not pass"):
        trial_score.load()


def test_without_a_flag_the_block_is_printed(
    folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    put(folder)
    assert trial_score.main([]) == 0
    assert capsys.readouterr().out == trial_score.render(trial_score.load()) + "\n"


def test_check_passes_when_the_block_is_what_the_scorer_renders(
    folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    put(folder)
    trial_score.DOCUMENT.write_text(
        trial_score.written(SKELETON, trial_score.render(trial_score.load()))
    )
    assert trial_score.main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


def test_check_fails_on_a_drifted_block(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    put(folder)
    drifted = trial_score.render(trial_score.load()).replace("5 repositories", "6 repositories")
    trial_score.DOCUMENT.write_text(trial_score.written(SKELETON, drifted))
    assert trial_score.main(["--check"]) == 1
    assert "stale" in capsys.readouterr().out


def test_check_fails_when_records_exist_and_the_document_has_no_section(folder: Path) -> None:
    put(folder)
    trial_score.DOCUMENT.write_text(SKELETON)
    assert trial_score.main(["--check"]) == 1


def test_check_fails_when_a_section_is_left_with_no_record(folder: Path) -> None:
    trial_score.DOCUMENT.write_text(trial_score.written(SKELETON, "stale"))
    assert trial_score.main(["--check"]) == 1


def test_with_no_record_and_no_section_the_check_passes(
    folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trial_score.DOCUMENT.write_text(SKELETON)
    assert trial_score.main(["--check"]) == 0
    assert trial_score.main([]) == 0
    assert "up to date" in capsys.readouterr().out


def test_write_puts_the_block_into_the_document_and_needs_a_record(folder: Path) -> None:
    trial_score.DOCUMENT.write_text(SKELETON)
    with pytest.raises(SystemExit, match="no record of the trial measurement"):
        trial_score.main(["--write"])
    put(folder)
    assert trial_score.main(["--write"]) == 0
    assert trial_score.main(["--check"]) == 0
    assert "## Upgrade trial" in trial_score.DOCUMENT.read_text()


def test_the_flags_are_exclusive(folder: Path) -> None:
    with pytest.raises(SystemExit):
        trial_score.main(["--check", "--write"])


def test_the_committed_document_has_the_block_the_committed_records_render() -> None:
    """With no record committed there is no section; with records, the block is theirs."""
    generated = trial_score.render(trial_score.load())
    published = trial_score.block(trial_score.DOCUMENT.read_text(encoding="utf-8"))
    assert published == (generated or None)


def test_every_committed_record_is_well_formed_and_names_its_frame() -> None:
    for path in sorted(trial_score.RECORDS.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        assert trial_box.validate_record(record) == [], path.name
        assert (trial_score.ROOT / record["frame"]).parent.name == path.stem
