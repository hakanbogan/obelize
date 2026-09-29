"""`docs/CLI.md` and `obelize.models` agree on the verify vocabularies and the exit table."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from obelize.models import (
    COMMAND_SOURCES,
    NO_VERDICT_EXPECTED,
    REASONS_BY_STATUS,
    VERIFY_REASONS,
    VERIFY_STATUSES,
    CommandResult,
    VerifyPhase,
    VerifyResult,
)
from obelize.verify import status

# The model refuses a `pass` over no command.
PASSED = CommandResult(command="true", source="cli", status="pass", exit_code=0, duration_ms=0)

# The model refuses `baseline_failed` over no baseline.
RED = VerifyPhase(
    status="fail",
    reason="command_failed",
    commands=(
        CommandResult(
            command="false",
            source="cli",
            status="fail",
            reason="command_failed",
            exit_code=1,
            duration_ms=0,
        ),
    ),
)

CLI = Path(__file__).resolve().parents[2] / "docs" / "CLI.md"
TEXT = CLI.read_text(encoding="utf-8")

_SUBSECTION = re.compile(r"^#### `([a-z.\[\]]+)` \((\d+) values\)$", re.MULTILINE)
_HEADING = re.compile(r"^#", re.MULTILINE)
_FIRST_CELL = re.compile(r"^\| `([a-z_]+)` \|", re.MULTILINE)


def _block(name: str) -> tuple[str, int]:
    """The text under `#### <name> (N values)` up to the next heading of any level, and N.

    Not just `####`: the configuration table that follows also starts rows with lower-case words.
    """
    for match in _SUBSECTION.finditer(TEXT):
        if match.group(1) != name:
            continue
        after = _HEADING.search(TEXT, match.end())
        end = after.start() if after else len(TEXT)
        return TEXT[match.end() : end], int(match.group(2))
    raise AssertionError(f"docs/CLI.md has no `{name}` vocabulary table")


def _table(name: str) -> tuple[set[str], int]:
    """The first column of that table, and the count its heading claims."""
    body, claimed = _block(name)
    return set(_FIRST_CELL.findall(body)), claimed


PUBLISHED = {
    "verify.status": VERIFY_STATUSES,
    "verify.reason": VERIFY_REASONS,
    "verify.commands[].source": COMMAND_SOURCES,
}


@pytest.mark.parametrize("name", sorted(PUBLISHED))
def test_the_page_and_the_code_hold_the_same_members(name: str) -> None:
    documented, _ = _table(name)
    assert documented == set(PUBLISHED[name]), (
        f"docs/CLI.md's `{name}` table and src/obelize/models.py disagree. Only in the "
        f"document: {sorted(documented - set(PUBLISHED[name]))}. Only in the code: "
        f"{sorted(set(PUBLISHED[name]) - documented)}. A member is added to both, in one commit."
    )


@pytest.mark.parametrize("name", sorted(PUBLISHED))
def test_a_heading_that_counts_its_members_counts_them_correctly(name: str) -> None:
    documented, claimed = _table(name)
    assert claimed == len(documented), f"`{name}` claims {claimed} and has {len(documented)}"


def test_every_reason_stands_under_the_status_the_page_puts_it_under() -> None:
    """Both tables could hold the right members yet file a reason under the wrong status."""
    body, _ = _block("verify.reason")
    rows = re.findall(r"^\| `([a-z_]+)` \| `([a-z_]+)` \|", body, re.MULTILINE)
    assert len(rows) == len(VERIFY_REASONS), rows
    paired: dict[str, set[str]] = {name: set() for name in VERIFY_STATUSES}
    for reason, under in rows:
        paired[under].add(reason)
    assert paired == {name: set(values) for name, values in REASONS_BY_STATUS.items()}


def test_the_status_to_exit_table_is_the_mapping_the_code_applies() -> None:
    """`n/a` is not `0`: a dry run with review items exits `4`, which a verify `0` contradicts."""
    block = TEXT.split("| `verify.status` | `verify.reason` | Exit | When |", 1)[1]
    block = block.split("\n\n", 1)[0]
    rows = re.findall(r"^\| `(\w+)` \| ([^|]+) \| (?:`(\d)`|n/a) \|", block, re.MULTILINE)
    assert len(rows) == 6, rows
    seen: set[tuple[str, str]] = set()
    for published_status, reasons, code in rows:
        for reason in re.findall(r"`([a-z_]+)`", reasons) or [""]:
            result = VerifyResult(
                status=published_status,
                reason=reason or None,
                commands=() if published_status != "pass" else (PASSED,),
                baseline=RED if reason == "baseline_failed" else None,
            )
            assert status.exit_code(result) == (int(code) if code else None), (
                f"{published_status}/{reason} should exit {code or 'n/a'}"
            )
            seen.add((published_status, reason))
    assert {reason for _, reason in seen} - {""} == set(VERIFY_REASONS)
    assert {reason for _, reason in seen if reason in NO_VERDICT_EXPECTED} == set(
        NO_VERDICT_EXPECTED
    )
