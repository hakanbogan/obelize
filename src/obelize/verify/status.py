"""What a verification concluded, and `exit_code`, the published table in `docs/CLI.md`."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from obelize.models import (
    NO_VERDICT_EXPECTED,
    VERIFY_STATUS_ORDER,
    CommandResult,
    ExitCode,
    VerifyPhase,
    VerifyRecord,
    VerifyResult,
    VerifyStatus,
)

# `not_run` is 6 like `inconclusive`: the no-verdict reasons and `policy_refused` (5) are handled
# first, so what reaches here was owed a verdict and did not get one.
_EXIT: dict[VerifyStatus, ExitCode] = {
    "pass": 0,
    "fail": 3,
    "inconclusive": 6,
    "not_run": 6,
}


def worst(statuses: Iterable[VerifyStatus]) -> VerifyStatus:
    """The worst of several, in `fail` > `inconclusive` > `not_run` > `pass`."""
    ranked = sorted(statuses, key=VERIFY_STATUS_ORDER.index)
    if not ranked:
        raise ValueError("a phase needs at least one command to have a worst status")
    return ranked[0]


def phase(results: Sequence[CommandResult]) -> VerifyPhase:
    """One phase's verdict: the worst status, and the reason of the first command that had it."""
    status = worst(row.status for row in results)
    return VerifyPhase(
        status=status,
        reason=next(row.reason for row in results if row.status == status),
        commands=tuple(results),
    )


def gate(baseline: VerifyPhase | None) -> VerifyResult | None:
    """The run's verdict when the baseline already settled it, else `None` (run the after-phase).

    A red suite is `baseline_failed`; a timeout or bad command keeps its own reason, as its fix
    differs. Asked first, so the after-phase is skipped; `decide` refuses a failing baseline.
    """
    if baseline is None or baseline.status == "pass":
        return None
    return VerifyResult(
        status="inconclusive",
        reason="baseline_failed" if baseline.status == "fail" else baseline.reason,
        baseline=baseline,
    )


def decide(after: VerifyPhase, *, baseline: VerifyPhase | None = None) -> VerifyResult:
    """The run's verdict once the after-phase has run, with its baseline beside it."""
    return VerifyResult(
        status=after.status,
        reason=after.reason,
        commands=after.commands,
        baseline=baseline,
    )


def settled(record: VerifyRecord) -> bool:
    """Whether a baseline that did not pass decided the run, so no after-phase can run again."""
    return record.baseline is not None and record.baseline.status != "pass"


def exit_code(result: VerifyResult | VerifyRecord) -> ExitCode | None:
    """`docs/CLI.md`'s status-to-exit table; `None` means no verdict was expected.

    `None`, not 0, so the plan's own outcome decides (an apply with review items exits 4).
    "Expected" is read off the reason, deliberately not a flag. One mapping for both documents.
    """
    if result.reason in NO_VERDICT_EXPECTED:
        return None
    if result.reason == "policy_refused":
        return 5
    return _EXIT[result.status]


__all__ = ["decide", "exit_code", "gate", "phase", "settled", "worst"]
