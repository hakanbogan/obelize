"""The verify status arithmetic, and every status/reason pair a model must refuse.

The refused pairs are the half no run can show: a run that produced one would be the bug.
"""

from __future__ import annotations

import itertools

import pytest
from pydantic import ValidationError

from obelize.models import (
    VERIFY_STATUS_ORDER,
    CommandResult,
    VerifyPhase,
    VerifyReason,
    VerifyResult,
    VerifyStatus,
)
from obelize.verify import status


def command(
    verdict: VerifyStatus = "pass", reason: str | None = None, code: int | None = 0
) -> CommandResult:
    return CommandResult(
        command="a-command",
        source="cli",
        status=verdict,
        reason=reason,
        exit_code=code,
        duration_ms=1,
    )


PASSED = command()
FAILED = command("fail", "command_failed", 1)
TIMED_OUT = command("inconclusive", "timeout", -9)
MISSING = command("inconclusive", "command_not_executable", None)


def test_the_order_is_the_one_the_documents_publish() -> None:
    assert VERIFY_STATUS_ORDER == ("fail", "inconclusive", "not_run", "pass")


@pytest.mark.parametrize(("left", "right"), list(itertools.combinations(VERIFY_STATUS_ORDER, 2)))
def test_the_worse_of_any_two_is_the_earlier_one(left: VerifyStatus, right: VerifyStatus) -> None:
    assert status.worst([left, right]) == left
    assert status.worst([right, left]) == left


def test_one_status_is_its_own_worst() -> None:
    assert status.worst(["pass"]) == "pass"


def test_there_is_no_worst_of_nothing() -> None:
    """A phase is at least one command, and an empty one is a caller's mistake."""
    with pytest.raises(ValueError, match="at least one command"):
        status.worst([])


def test_a_phase_takes_the_worst_command_and_that_command_s_reason() -> None:
    phase = status.phase([PASSED, TIMED_OUT, FAILED])
    assert (phase.status, phase.reason) == ("fail", "command_failed")
    assert phase.commands == (PASSED, TIMED_OUT, FAILED)


def test_the_reason_is_the_first_of_the_worst_and_not_the_last() -> None:
    """First in run order: what a reader sees first, and independent of any sorting."""
    assert status.phase([TIMED_OUT, MISSING]).reason == "timeout"
    assert status.phase([MISSING, TIMED_OUT]).reason == "command_not_executable"


def test_a_phase_where_everything_passed_has_no_reason() -> None:
    assert status.phase([PASSED, PASSED]).reason is None


def test_no_baseline_and_a_green_baseline_both_let_the_run_through() -> None:
    assert status.gate(None) is None
    assert status.gate(status.phase([PASSED])) is None


def test_a_baseline_that_failed_withholds_the_verdict() -> None:
    settled = status.gate(status.phase([FAILED]))
    assert settled is not None
    assert (settled.status, settled.reason) == ("inconclusive", "baseline_failed")
    assert settled.commands == ()


def test_a_baseline_that_produced_no_verdict_keeps_its_own_reason() -> None:
    """A red suite and a slow one need different next actions, so different reasons."""
    settled = status.gate(status.phase([TIMED_OUT]))
    assert settled is not None
    assert (settled.status, settled.reason) == ("inconclusive", "timeout")


def test_the_after_phase_carries_its_baseline_beside_it() -> None:
    baseline = status.phase([PASSED])
    result = status.decide(status.phase([FAILED]), baseline=baseline)
    assert (result.status, result.reason) == ("fail", "command_failed")
    assert result.baseline == baseline


def test_a_caller_that_skipped_the_gate_cannot_build_the_result() -> None:
    with pytest.raises(ValidationError, match="gates the run"):
        status.decide(status.phase([PASSED]), baseline=status.phase([FAILED]))


REFUSED = [
    ({"status": "pass", "reason": "command_failed"}, "not a reason"),
    ({"status": "fail"}, "says why"),
    ({"status": "fail", "reason": "timeout"}, "not a reason"),
    ({"status": "inconclusive", "reason": "policy_refused"}, "not a reason"),
    ({"status": "not_run", "reason": "timeout"}, "not a reason"),
    ({"status": "pass"}, "a pass over no command"),
    (
        {"status": "not_run", "reason": "policy_refused", "commands": (PASSED,)},
        "nothing ran",
    ),
    ({"status": "inconclusive", "reason": "baseline_failed"}, "over no baseline"),
]


@pytest.mark.parametrize(("fields", "message"), REFUSED, ids=[m for _, m in REFUSED])
def test_a_result_that_cannot_be_true_cannot_be_built(
    fields: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        VerifyResult(**fields)


def test_baseline_failed_may_not_be_claimed_over_a_baseline_that_passed() -> None:
    with pytest.raises(ValidationError, match="a baseline that passed"):
        VerifyResult(
            status="inconclusive",
            reason="baseline_failed",
            baseline=status.phase([PASSED]),
        )


def test_baseline_failed_may_not_be_claimed_over_a_baseline_that_timed_out() -> None:
    """The reason names what happened, so it may not be borrowed for a near miss."""
    with pytest.raises(ValidationError, match="did not fail"):
        VerifyResult(
            status="inconclusive",
            reason="baseline_failed",
            baseline=status.phase([TIMED_OUT]),
        )


@pytest.mark.parametrize("reason", ["dry_run", "no_verify_commands", "policy_refused"])
def test_a_run_where_nothing_ran_has_no_baseline_either(reason: VerifyReason) -> None:
    """Only a write refused after the tests, below, keeps one under `not_run`."""
    with pytest.raises(ValidationError, match="no baseline ran"):
        VerifyResult(status="not_run", reason=reason, baseline=status.phase([PASSED]))


def test_a_write_refused_after_the_baseline_keeps_the_baseline_that_ran() -> None:
    """Nothing was written to verify, and the tests before it still ran."""
    for before in (PASSED, FAILED):
        kept = VerifyResult(
            status="not_run", reason="no_changes_to_verify", baseline=status.phase([before])
        )
        assert kept.baseline == status.phase([before])


def test_a_phase_may_not_hold_a_pair_the_table_does_not() -> None:
    with pytest.raises(ValidationError, match="not a reason"):
        VerifyPhase(status="not_run", reason="tree_changed")


IMPOSSIBLE = [
    ({"status": "not_run"}, "what running a command produced"),
    ({"status": "fail", "reason": "command_failed", "exit_code": 0}, "does not read as"),
    ({"status": "pass", "exit_code": 1}, "does not read as"),
    (
        {"status": "fail", "reason": "policy_refused", "exit_code": 1},
        "statement about the run",
    ),
    ({"status": "fail", "exit_code": 1}, "cannot both be right"),
    (
        {"status": "inconclusive", "reason": "timeout", "exit_code": None},
        "never became a process",
    ),
    (
        {"status": "inconclusive", "reason": "command_not_executable", "exit_code": -9},
        "never became a process",
    ),
]


@pytest.mark.parametrize(("fields", "message"), IMPOSSIBLE, ids=[m for _, m in IMPOSSIBLE])
def test_a_command_result_that_cannot_be_true_cannot_be_built(
    fields: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        CommandResult(command="a-command", source="cli", duration_ms=1, **fields)
