"""One verification phase and the commands it ran, as the run folder records them."""

from __future__ import annotations

from pydantic import Field, model_validator

from obelize.models.fields import RelativePath, RunnableCommand, _Frozen
from obelize.models.vocabulary import (
    COMMAND_REASONS,
    REASONS_BY_STATUS,
    CommandSource,
    VerifyReason,
    VerifyStatus,
)


def _check_command(
    status: VerifyStatus, reason: VerifyReason | None, exit_code: int | None
) -> None:
    """What a row about one command may not say; shared so result and record cannot disagree."""
    if status == "not_run":
        raise ValueError("a command result is what running a command produced")
    if (reason is None) != (status == "pass"):
        raise ValueError(f"{status!r} and reason {reason!r} cannot both be right")
    if reason is not None and reason not in COMMAND_REASONS:
        raise ValueError(f"{reason!r} is a statement about the run, not about a command")
    # A command killed at its deadline may exit 0, and that code is not a verdict.
    if reason != "timeout" and (exit_code == 0) != (status == "pass"):
        raise ValueError(f"exit code {exit_code!r} does not read as {status!r}")
    if (exit_code is None) != (reason == "command_not_executable"):
        raise ValueError("a command has no exit code exactly when it never became a process")


def _check_phase(status: VerifyStatus, reason: VerifyReason | None, commands: int) -> None:
    """What one phase may conclude, held by `VerifyPhase` and by its record."""
    allowed = REASONS_BY_STATUS[status]
    if reason is None:
        if allowed:
            raise ValueError(f"{status!r} says why it is not a pass; this one does not")
    elif reason not in allowed:
        raise ValueError(f"{reason!r} is not a reason a {status!r} can carry")
    if status == "not_run" and commands:
        raise ValueError("nothing ran, so there is no command to record")
    if status == "pass" and not commands:
        raise ValueError("a pass over no command is not a pass")


def _check_gate(
    status: VerifyStatus,
    reason: VerifyReason | None,
    commands: int,
    baseline: VerifyStatus | None,
) -> None:
    """An invariant held by `VerifyResult` and by its record.

    A write refused after the baseline keeps it: nothing is left to verify, and the tests ran.
    """
    if baseline is None:
        if reason == "baseline_failed":
            raise ValueError("baseline_failed over no baseline")
        return
    if status == "not_run":
        if reason == "no_changes_to_verify":
            return
        raise ValueError("nothing ran, so no baseline ran either")
    if baseline == "pass":
        if reason == "baseline_failed":
            raise ValueError("baseline_failed over a baseline that passed")
        return
    if reason == "baseline_failed" and baseline != "fail":
        raise ValueError(f"the baseline did not fail, it was {baseline!r}")
    if status != "inconclusive" or commands:
        raise ValueError(
            "a baseline that did not pass gates the run: the after-phase does not run "
            "and what it would have said is not evidence about the patch"
        )


class CommandResult(_Frozen):
    """One verification command, and what running it produced.

    Only exit 0 passes; no exit code means it never became a process (a killed one's is
    negative); a reason is set exactly when it did not pass, and only a command-level one.
    """

    command: RunnableCommand
    source: CommandSource
    status: VerifyStatus
    reason: VerifyReason | None = None
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    output: str = ""
    truncated: bool = False
    junit: str | None = None
    # Found on PATH inside obelize's own environment; a flag, as a path would name the machine.
    in_obelize_environment: bool = False

    @model_validator(mode="after")
    def _check(self) -> CommandResult:
        _check_command(self.status, self.reason, self.exit_code)
        return self


class VerifyPhase(_Frozen):
    """What one phase concluded: the before-patch run, or the after-patch one.

    `obelize.verify.status` derives status and reason; this refuses pairs that cannot be true,
    including a `pass` over no command.
    """

    status: VerifyStatus
    reason: VerifyReason | None = None
    commands: tuple[CommandResult, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> VerifyPhase:
        _check_phase(self.status, self.reason, len(self.commands))
        return self


class VerifyResult(VerifyPhase):
    """`run.json`'s `verify` object: the after-phase, plus the baseline gate.

    `baseline` is one level deep. A baseline that did not pass makes the run `inconclusive` and
    skips the after-phase; `baseline_failed` needs a baseline that failed, not one
    that timed out.
    """

    baseline: VerifyPhase | None = None

    @model_validator(mode="after")
    def _check_the_baseline(self) -> VerifyResult:
        _check_gate(
            self.status,
            self.reason,
            len(self.commands),
            None if self.baseline is None else self.baseline.status,
        )
        return self


class CommandRecord(_Frozen):
    """One command in `run.json`'s `verify.commands[]`, with its output as a log path."""

    command: RunnableCommand
    source: CommandSource
    status: VerifyStatus
    reason: VerifyReason | None = None
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    truncated: bool = False
    # Run-folder-relative. Output stays out of run.json, which bug reports attach; `CommandResult`
    # holds the output itself and a bare junit file name.
    log: RelativePath | None = None
    junit: RelativePath | None = None
    in_obelize_environment: bool = False

    @classmethod
    def of(cls, result: CommandResult, *, log: str | None, junit: str | None) -> CommandRecord:
        """One result, with the two places the writer put its files."""
        if log is None and result.output:
            raise ValueError(
                f"{result.command!r} printed something and the record names no log; the "
                f"output would be the one thing this row exists to point at"
            )
        return cls(
            command=result.command,
            source=result.source,
            status=result.status,
            reason=result.reason,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            truncated=result.truncated,
            log=log,
            junit=junit,
            in_obelize_environment=result.in_obelize_environment,
        )

    @model_validator(mode="after")
    def _check(self) -> CommandRecord:
        _check_command(self.status, self.reason, self.exit_code)
        return self


class VerifyPhaseRecord(_Frozen):
    """One verification phase as `run.json` records it, with command output as log paths."""

    status: VerifyStatus
    reason: VerifyReason | None = None
    commands: tuple[CommandRecord, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> VerifyPhaseRecord:
        _check_phase(self.status, self.reason, len(self.commands))
        return self


class VerifyRecord(VerifyPhaseRecord):
    """The `verify` object of `run.json`: the after-patch phase plus the baseline that gates it."""

    baseline: VerifyPhaseRecord | None = None

    @model_validator(mode="after")
    def _check_the_baseline(self) -> VerifyRecord:
        _check_gate(
            self.status,
            self.reason,
            len(self.commands),
            None if self.baseline is None else self.baseline.status,
        )
        return self


__all__ = [
    "CommandRecord",
    "CommandResult",
    "VerifyPhase",
    "VerifyPhaseRecord",
    "VerifyRecord",
    "VerifyResult",
]
