"""Which withheld rows are asked about, with what context, and which are not, per `answers.yaml`.

`app` has nothing withheld, so it can only fail by over-asking. Each repository is driven once, on
a copy: a run folder left under `tests/fixtures/` would be picked up by the next scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import harness
import pytest
import yaml

from obelize.models import WITHHELD
from obelize.providers import base

ROOT = Path(__file__).resolve().parents[2]
KEY: dict[str, Any] = yaml.safe_load(
    (ROOT / "tests" / "fixtures" / "providers" / "answers.yaml").read_text(encoding="utf-8")
)
CASES: dict[str, dict[str, Any]] = {case["case"]: case for case in KEY["cases"]}
NAMES = sorted(CASES)


@dataclass(frozen=True, slots=True)
class Driven:
    """One driven repository; `inputs` lets `consult` rerun without driving it again."""

    asked: list[base.Consultation]
    skipped: list[base.Skipped]
    withheld: int
    inputs: dict[str, Any]


def _drive(case: dict[str, Any], work: Path) -> Driven:
    _, inputs = harness.driven(ROOT / KEY["repositories"][case["repository"]], work, KEY["pack"])
    asked, skipped = base.questions(**inputs)
    return Driven(
        asked=asked,
        skipped=skipped,
        withheld=sum(1 for row in inputs["findings"] if row.scan_status in WITHHELD),
        inputs=inputs,
    )


@pytest.fixture(scope="module")
def driven(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Driven]:
    return {
        name: _drive(CASES[name], tmp_path_factory.mktemp(f"providers-{name}")) for name in NAMES
    }


@pytest.mark.parametrize("name", NAMES)
def test_the_questions_are_the_ones_the_key_names(name: str, driven: dict[str, Driven]) -> None:
    """Document order is graded, or `model/` file numbering could differ between two runs."""
    expected = [(row["path"], row["line"]) for row in CASES[name]["consulted"]]
    assert [(one.context.path, one.line) for one in driven[name].asked] == expected


@pytest.mark.parametrize("name", NAMES)
def test_the_refusals_are_the_ones_the_key_names(name: str, driven: dict[str, Driven]) -> None:
    expected = [(row["path"], row["line"], row["reason"]) for row in CASES[name]["skipped"]]
    assert [(one.path, one.line, one.reason) for one in driven[name].skipped] == expected


@pytest.mark.parametrize("name", NAMES)
def test_every_withheld_row_is_either_asked_or_named(name: str, driven: dict[str, Driven]) -> None:
    result = driven[name]
    assert len(result.asked) + len(result.skipped) == result.withheld


@pytest.mark.parametrize("name", NAMES)
def test_the_question_carries_the_bail_the_key_records(
    name: str, driven: dict[str, Driven]
) -> None:
    expected = [row["bail"] for row in CASES[name]["consulted"]]
    assert [one.bail for one in driven[name].asked] == expected


@pytest.mark.parametrize("name", NAMES)
def test_the_context_is_the_range_the_key_names(name: str, driven: dict[str, Driven]) -> None:
    """Ends are compared as text too, so the wrong file or zero-based numbering fails here."""
    for one, row in zip(driven[name].asked, CASES[name]["consulted"], strict=True):
        where = f"{row['path']}:{row['line']}"
        assert (one.context.start_line, one.context.end_line) == (
            row["start_line"],
            row["end_line"],
        ), where
        lines = one.context.text.splitlines()
        assert lines[0] == row["first"], where
        assert lines[-1] == row["last"], where


@pytest.mark.parametrize("name", NAMES)
def test_the_context_is_within_the_budget(name: str, driven: dict[str, Driven]) -> None:
    """No arm may exceed it; a larger context is skipped as `context_too_large`."""
    for one in driven[name].asked:
        span = one.context.end_line - one.context.start_line + 1
        assert span <= base.CONTEXT_LINE_LIMIT
        assert one.context.holds(one.line, one.line)


@pytest.mark.parametrize("name", NAMES)
def test_the_question_carries_the_packs_own_words(name: str, driven: dict[str, Driven]) -> None:
    """`to.package` and the pack's limitations are ADR-003's "pack note"."""
    for one in driven[name].asked:
        assert one.pack_id == KEY["pack"]
        assert one.to_package == "google-genai"
        assert one.limitations


def test_nothing_is_asked_about_a_repository_with_nothing_withheld(
    driven: dict[str, Driven],
) -> None:
    """ADR-003's first trust rule: no model is asked about code the rules already rewrote."""
    result = driven["app"]
    assert (result.asked, result.skipped, result.withheld) == ([], [], 0)


def test_a_provider_is_called_once_per_question_and_never_otherwise(
    driven: dict[str, Driven],
) -> None:
    """Drives `consult`, not `questions`: nothing between selection and adapter repeats or skips."""
    for name in ("app", "example"):
        spy = _Spy()
        result = base.consult(spy, **driven[name].inputs)
        assert [one.line for one in spy.seen] == [one.line for one in driven[name].asked]
        assert len(result.answers) == len(spy.seen)
        assert result.proposals == ()


class _Spy:
    """Answers nothing; deliberately inherits nothing, since the seam is a `Protocol`."""

    def __init__(self) -> None:
        self.seen: list[base.Consultation] = []

    def request(self, consultation: base.Consultation) -> bytes:
        return b"{}"

    def propose(self, consultation: base.Consultation) -> base.Reply:
        self.seen.append(consultation)
        return base.Reply(proposal=None)


@pytest.mark.parametrize("entry", KEY["redaction"], ids=lambda entry: entry["path"])
def test_the_credential_does_not_travel(entry: dict[str, Any], driven: dict[str, Driven]) -> None:
    """TM-3's payload half; `present` rules out an empty context or the wrong range."""
    asked = [
        one
        for one in driven[entry["case"]].asked
        if one.context.path == entry["path"] and one.line == entry["line"]
    ]
    assert len(asked) == 1
    text = asked[0].context.text
    assert entry["absent"] not in text
    assert entry["present"] in text
