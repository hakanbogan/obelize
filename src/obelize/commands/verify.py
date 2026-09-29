"""`obelize verify`: the same phase again, over a run folder that exists.

A baseline that did not pass settles it without re-running. Commands come from the
configuration, never `run.json`: a forged run folder must not choose what obelize runs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from obelize import fsutil
from obelize.commands import CommandError, reports
from obelize.evidence import report, run_dir
from obelize.models import VerifyResult
from obelize.verify import runner as verifier
from obelize.verify import status as verdicts

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Mapping

    from obelize.models import Config, ExitCode, RunRecord, VerifyRecord


@dataclass(frozen=True, slots=True)
class Request:
    root: Path
    run_id: str
    config: Config
    cli_commands: tuple[str, ...]
    mode: verifier.Mode
    config_dir: Path
    environ: Mapping[str, str]
    ask: Callable[[str], bool] | None = None


@dataclass(frozen=True, slots=True)
class Outcome:
    """The verdict and the folder; `rewritten` is false only when the baseline gated the run."""

    exit_code: ExitCode
    record: RunRecord
    evidence: str
    rewritten: bool = True


def run(request: Request) -> Outcome:
    """Re-run one run's after-phase and put the answer back in its folder."""
    try:
        loaded = run_dir.load(request.root, request.run_id)
    except run_dir.EvidenceError as error:
        raise CommandError(str(error), 2) from error
    recorded = _verifiable(loaded.record)

    if verdicts.settled(recorded):
        # Settled already: nothing ran at fix time and nothing runs now; the record answers.
        return Outcome(
            exit_code=_expected(recorded),
            record=loaded.record,
            evidence=loaded.relative,
            rewritten=False,
        )

    began = time.monotonic()
    with TemporaryDirectory(prefix="obelize-verify-", ignore_cleanup_errors=True) as scratch:
        junit = Path(scratch)
        result = _stale(request, loaded.record) or _run(request, junit)
        verified = run_dir.verification(result, after_junit=reports(junit))

    code = _expected(verified.record)
    record = run_dir.reverified(loaded.record, verified, exit_code=code, ms=_ms(began))
    try:
        run_dir.rewrite(loaded, record, verified, _note(loaded, record))
    except run_dir.EvidenceError as error:
        raise CommandError(str(error), 1) from error
    return Outcome(exit_code=code, record=record, evidence=loaded.relative)


def _stale(request: Request, record: RunRecord) -> VerifyResult | None:
    """`inconclusive` / `tree_changed`, or `None` when every file the run wrote is unchanged."""
    for row in record.file_edits:
        # The name first: read by path, Windows opens `aux.py` as a device.
        if fsutil.unusable(row.path) or _digest(request.root / row.path) != row.after_sha256:
            return VerifyResult(status="inconclusive", reason="tree_changed")
    return None


def _run(request: Request, junit: Path) -> VerifyResult:
    """The after-phase; the trust ladder is asked only here, so no-op runs refuse nothing."""
    permitted = verifier.resolve(
        request.root,
        mode=request.mode,
        config_dir=request.config_dir,
        cli_commands=request.cli_commands,
        repo_commands=request.config.verify.commands,
        ask=request.ask,
    )
    if isinstance(permitted, verifier.Refused):
        return VerifyResult(status="not_run", reason="policy_refused")
    if not permitted.commands:
        return VerifyResult(status="not_run", reason="no_verify_commands")
    return verdicts.decide(
        verdicts.phase(
            verifier.run(
                request.root,
                permitted.commands,
                timeout_s=request.config.verify.timeout_s,
                environ=request.environ,
                junit_dir=junit if request.config.verify.junit else None,
            )
        )
    )


def _expected(record: VerifyRecord) -> ExitCode:
    """`docs/CLI.md`'s exit table, which is total for this command.

    Only `dry_run` and `no_changes_to_verify` give no code, and `_verifiable` refused both, so
    the assert below narrows a type.
    """
    code = verdicts.exit_code(record)
    assert code is not None  # noqa: S101 - see above
    return code


def _verifiable(record: RunRecord) -> VerifyRecord:
    """This run's verification, or a usage error (exit 2) when it has no after-state."""
    if record.mode != "apply":
        raise CommandError(
            f"{record.run_id} is a {record.mode!r} run: it wrote no file, so there is "
            f"nothing to verify. Run obelize fix --apply to produce one.",
            2,
        )
    if not record.file_edits:
        raise CommandError(
            f"{record.run_id} wrote no file, so there is nothing to verify.",
            2,
        )
    # `RunRecord` refuses an apply with no verification, so this narrows a type.
    assert record.verify is not None  # noqa: S101 - see above
    return record.verify


def _note(loaded: run_dir.Loaded, record: RunRecord) -> str | None:
    """`REPORT.md` with its superseding block, or `None` to leave an unreadable one alone."""
    try:
        document = loaded.folder.read("REPORT.md").decode("utf-8")
    except OSError:
        return None
    return report.superseded(document, record, run_dir.instant(run_dir.now()))


def _digest(path: Path) -> str | None:
    """The sha256 at this path now, or `None` if nothing is there."""
    try:
        return fsutil.sha256(fsutil.read(path))
    except OSError:
        return None


def _ms(since: float) -> int:
    return int((time.monotonic() - since) * 1000)


__all__ = ["Outcome", "Request", "run"]
