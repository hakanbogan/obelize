"""`obelize fix`: the plan, the write, the verification and the evidence, in a fixed order.

The tree gate runs before the model and the baseline, so a refused apply sends no source and
spends no test suite. A refused verify command still writes (exit 5), since writing nothing would
look like a repository needing no work; a failed baseline still writes and skips the after-phase.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from obelize import __version__, fsutil, gitutil
from obelize.commands import CommandError, reports
from obelize.evidence import report, run_dir
from obelize.models import FindingsDocument, ModelConfig, VerifyPhase, VerifyResult
from obelize.packs import loader
from obelize.providers import base as providers
from obelize.providers import openai_compat, proposals
from obelize.scan import manifests
from obelize.scan import runner as scanner
from obelize.transforms import codemod
from obelize.verify import cheap
from obelize.verify import runner as verifier
from obelize.verify import status as verdicts

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Mapping, Sequence

    from obelize.fsutil import Apply, Change
    from obelize.models import (
        Config,
        ConfigOrigin,
        ExitCode,
        PlanDocument,
        ProposalRecord,
        RunModel,
        RunRecord,
        ScanSpec,
        VerifyReason,
    )
    from obelize.packs.loader import LoadedPack
    from obelize.scan.runtime import Blocked


@dataclass(frozen=True, slots=True)
class Request:
    """One `obelize fix` with every decision taken; `obelize.cli` reads terminal and environment."""

    root: Path
    # The packs to try: those the user named, or every one known. A named pack always runs; an
    # unnamed one only when the repository gives it something to say.
    packs: tuple[LoadedPack, ...]
    named: bool
    config: Config
    source: ConfigOrigin
    # Before the merge: the trust ladder needs to know which commands the user typed.
    cli_commands: tuple[str, ...]
    mode: verifier.Mode
    config_dir: Path
    environ: Mapping[str, str]
    argv: tuple[str, ...]
    apply: bool = False
    # Model proposals are written only with this and `--apply`.
    accept_model: bool = False
    ask: Callable[[str], bool] | None = None
    # The user's own block with `--model` over it; never the repository's.
    model: ModelConfig = field(default_factory=ModelConfig)
    # Whether a flag, and not only the user's file, asked for the model.
    model_flagged: bool = False


@dataclass(frozen=True, slots=True)
class Outcome:
    """What the run produced, for a caller that only prints."""

    exit_code: ExitCode
    record: RunRecord
    plan: PlanDocument
    # `plan.json`'s exact bytes, so `--json` and the file in the folder are one string.
    document: str
    # `patch.diff`'s bytes, which a dry run prints.
    patch: bytes
    evidence: str
    # Each declaration that blocked a pack, which names the file to change.
    blocked: tuple[Blocked, ...]
    # What the run did without being asked to say so, for a caller that prints it.
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Phases:
    """What happened to the disk and the tests, and how long each took."""

    applied: Apply | None
    verified: run_dir.Verified
    apply_ms: int | None = None
    verify_ms: int | None = None


@dataclass(frozen=True, slots=True)
class _Model:
    """The consultation folded into the run, and its clock."""

    run: codemod.Run
    session: proposals.Session | None = None
    ms: int | None = None


def run(request: Request) -> Outcome:
    """One `obelize fix`, from the walk to `.obelize/latest`."""
    started = run_dir.now()
    began = time.monotonic()
    chosen = select(request.root, request.config, request.packs, named=request.named, jobs=None)
    scan_ms = _ms(began)

    planning = time.monotonic()
    passes = _fold(request, chosen)
    driven = codemod.chained([(one.loaded.pack.id, one.run) for one in passes])
    scan = scanner.merged([one.scan for one in passes], chosen.tree)
    plan_ms = _ms(planning)

    gating = time.monotonic()
    stopped = (
        fsutil.gate(request.root, _changes(driven), allow_dirty=request.config.allow_dirty)
        if request.apply
        else None
    )
    gate_ms = _ms(gating)

    notes: tuple[str, ...] = ()
    if not passes:
        notes = (f"No pack applies. Checked: {', '.join(chosen.tried) or 'none'}.",)
    if len(passes) > 1 and request.model.provider != "none":
        if request.model_flagged:
            raise CommandError(
                "a model is asked about one pack's rows, so --model and --accept-model need "
                f"--pack to name one; this run uses {len(passes)}: "
                f"{', '.join(one.loaded.pack.id for one in passes)}.",
                2,
            )
        notes = ("The configured model was not asked: this run uses more than one pack.",)
        model = _Model(driven)
    elif whole := [one.loaded.pack.id for one in passes if _whole(one.loaded)]:
        if request.model.provider != "none":
            # A proposal is one row, and a pack whose one distribution holds both APIs moves the
            # whole repository or none of it.
            if request.model_flagged:
                raise CommandError(
                    f"a model's proposal is one row, and {whole[0]} moves a whole repository or "
                    f"none of it, so --model and --accept-model do not apply to it.",
                    2,
                )
            notes = (f"The configured model was not asked: {whole[0]} moves a whole repository.",)
        model = _Model(driven)
    else:
        model = _consulted(request, passes, driven, stopped)
    driven = model.run

    replanning = time.monotonic()
    loaded = [one.loaded for one in passes]
    plan = run_dir.planned(driven, loaded, None if model.session is None else model.session.numbers)
    plan_ms += _ms(replanning)

    # Before the write, or `git_dirty` would report obelize's own migration.
    state = gitutil.state(request.root)
    writable = _writable(request, plan, model.session)
    run_id = run_dir.new_id(started)
    journaled = _journaled(request, run_id, plan)
    phases = _phases(request, writable, stopped, gate_ms)
    code = _exit(phases, outstanding=bool(report.withheld_rows(driven.findings)), idle=not passes)
    recorded = _recorded(request, model, phases.applied)
    used = [
        run_dir.Used(one.loaded, one.scan.blocked[0] if one.scan.blocked else None)
        for one in passes
    ]
    record = run_dir.compose_fix(
        run_id=run_id,
        scan=scan,
        run=driven,
        plan=plan,
        verified=phases.verified,
        packs=used,
        config=request.config,
        source=request.source,
        git=state,
        argv=request.argv,
        applied=phases.applied,
        model=None if recorded is None else recorded[0],
        exit_code=code,
        started=started,
        finished=run_dir.now(),
        total_ms=_ms(began),
        scan_ms=scan_ms,
        plan_ms=plan_ms,
        apply_ms=phases.apply_ms,
        verify_ms=phases.verify_ms,
        model_ms=model.ms,
    )
    findings = FindingsDocument(
        obelize_version=__version__,
        packs=run_dir.refs(loaded),
        counts=scan.counts,
        findings=scan.findings,
    )
    artefacts = run_dir.artefacts(
        plan, phases.verified, phases.applied, () if recorded is None else recorded[1]
    )
    try:
        written = run_dir.write(
            request.root,
            record,
            findings.model_dump_json(indent=2) + "\n",
            loaded,
            report.document(
                record, scan, driven, plan.document, () if recorded is None else recorded[2]
            ),
            artefacts,
            journaled=journaled,
        )
    except run_dir.EvidenceError as error:
        # Exit 1 as `obelize scan` does; here the repository may already have changed.
        raise CommandError(str(error), 1) from error
    return Outcome(
        exit_code=code,
        record=record,
        plan=plan.document,
        document=artefacts.plan,
        patch=artefacts.patch,
        evidence=written.relative,
        blocked=scan.blocked,
        notes=notes,
    )


@dataclass(frozen=True, slots=True)
class Scanned:
    """A pack and what it found in the one read of the repository."""

    loaded: LoadedPack
    scan: scanner.Scan


@dataclass(frozen=True, slots=True)
class Chosen:
    """The repository read once, and the packs that run over it, in id order."""

    tree: scanner.Tree
    packs: tuple[Scanned, ...]
    # Every pack tried, so a run that finds none can say which it asked.
    tried: tuple[str, ...]


def select(
    root: Path,
    config: Config,
    packs: Sequence[LoadedPack],
    *,
    named: bool,
    jobs: int | None,
) -> Chosen:
    """Read `root` once, scan with every pack, and keep the named ones or those with a row.

    Two packs that cannot run together (`loader.conflict`) are refused, since the order between
    them would decide what is written.
    """
    ordered = sorted(packs, key=lambda loaded: loaded.pack.id)
    specs = [loader.to_scan_spec(loaded) for loaded in ordered]
    tree = scanner.read(root, config, specs)
    scans = [
        Scanned(loaded, scanner.scan(root, config, spec, jobs=jobs, tree=tree))
        for loaded, spec in zip(ordered, specs, strict=True)
    ]
    kept = tuple(one for one in scans if named or scanner.applies(one.scan))
    for index, first in enumerate(kept):
        for second in kept[index + 1 :]:
            reason = loader.conflict(first.loaded.pack, second.loaded.pack)
            if reason is not None:
                raise CommandError(f"{reason}; run them one at a time with --pack.", 2)
    return Chosen(tree, kept, tuple(one.loaded.pack.id for one in scans))


@dataclass(frozen=True, slots=True)
class _Pass:
    """One pack's turn: its scan (of the tree as the packs before it left it) and what it plans."""

    loaded: LoadedPack
    scan: scanner.Scan
    run: codemod.Run


def _fold(request: Request, chosen: Chosen) -> list[_Pass]:
    """The packs in id order, each over what the ones before it wrote, in memory.

    A pack is scanned again only when an earlier one wrote a file it has a row in, whose lines
    have then moved.
    """
    current = chosen.tree
    written: set[str] = set()
    passes: list[_Pass] = []
    for one in chosen.packs:
        spec = loader.to_scan_spec(one.loaded)
        scan = one.scan
        if written & {row.path for row in scan.findings if row.scan_status != "not_a_usage"}:
            scan = scanner.scan(request.root, request.config, spec, jobs=None, tree=current)
        driven = _driven(current, scan, one.loaded, spec)
        if scan.blocked:
            driven = codemod.blocked(driven, scan.blocked[0].reason)
        passes.append(_Pass(one.loaded, scan, driven))
        changed = {outcome.path: outcome.after for outcome in driven.written}
        if changed:
            current = current.with_bytes(changed)
            written.update(changed)
    return passes


def _driven(
    tree: scanner.Tree, scan: scanner.Scan, loaded: LoadedPack, spec: ScanSpec
) -> codemod.Run:
    """Every rule of one pack over the tree, as one value."""
    sources = {path: entry.data for path, entry in tree.entries.items() if entry.data is not None}
    try:
        return codemod.run(scan, sources, loaded.pack, spec)
    except codemod.CodemodError as error:
        raise CommandError(f"the run could not be planned: {error}. Nothing was written.", 1) from (
            error
        )


def _journaled(request: Request, run_id: str, plan: run_dir.Planned) -> bool:
    """The run folder and a copy of every original, before the first byte is written."""
    if not request.apply:
        return False
    try:
        run_dir.journal(request.root, run_id, plan)
    except run_dir.EvidenceError as error:
        raise CommandError(str(error), 1) from error
    return True


def _changes(driven: codemod.Run) -> tuple[Change, ...]:
    """What the deterministic rules would write, for the gate asked before the model."""
    return tuple(
        fsutil.Change(path=outcome.path, before=outcome.before, after=outcome.after)
        for outcome in driven.written
    )


def _whole(loaded: LoadedPack) -> bool:
    """Whether the pack's one distribution holds both APIs, so only the whole repository moves."""
    return manifests.coupled(loader.to_scan_spec(loaded))


def _consulted(
    request: Request, passes: Sequence[_Pass], driven: codemod.Run, stopped: Apply | None
) -> _Model:
    """The model pass; none without a provider, a pack or after a gate refusal, nothing is sent."""
    provider = openai_compat.build(request.model, request.environ)
    if provider is None or stopped is not None or not passes:
        return _Model(driven)
    consulting = time.monotonic()
    session = proposals.consult(
        provider,
        request.model,
        root=request.root,
        findings=driven.findings,
        plans=driven.plans,
        sources={outcome.path: outcome.before for outcome in driven.files},
        pack=passes[0].loaded.pack,
        environ=request.environ,
    )
    return _Model(proposals.folded(driven, session), session, _ms(consulting))


def _writable(
    request: Request, plan: run_dir.Planned, session: proposals.Session | None
) -> tuple[Change, ...]:
    """The plan minus model proposals `--accept-model` did not permit."""
    if session is None:
        return plan.changes
    return proposals.writable(
        plan.changes, session, apply=request.apply, accept=request.accept_model
    )


def _recorded(
    request: Request, model: _Model, applied: Apply | None
) -> tuple[RunModel, tuple[tuple[str, bytes], ...], tuple[ProposalRecord, ...]] | None:
    """`run.json`'s `model`, the `model/` files and their rows; after the phases."""
    if model.session is None:
        return None
    rows = proposals.records(
        model.session, applied=applied, apply=request.apply, accept=request.accept_model
    )
    summary = proposals.summary(model.session, rows)
    return summary, proposals.artefacts(proposals.document(model.session, summary), rows), rows


def context(request: Request) -> list[str]:
    """`--show-context`: what would be sent; no request, no run folder, no write."""
    chosen = select(request.root, request.config, request.packs, named=request.named, jobs=None)
    if len(chosen.packs) != 1:
        raise CommandError(
            f"--show-context needs exactly one pack; this repository has {len(chosen.packs)}. "
            f"Name one with --pack.",
            2,
        )
    one = chosen.packs[0]
    if _whole(one.loaded):
        raise CommandError(
            f"--show-context: {one.loaded.pack.id} moves a whole repository or none of it, so no "
            f"model is asked about it.",
            2,
        )
    driven = _driven(chosen.tree, one.scan, one.loaded, loader.to_scan_spec(one.loaded))
    asked, skipped = providers.questions(
        findings=driven.findings,
        plans=driven.plans,
        sources={outcome.path: outcome.before for outcome in driven.files},
        pack=one.loaded.pack,
        environ=request.environ,
    )
    return proposals.shown(request.model, asked, skipped)


def _phases(
    request: Request, changes: Sequence[Change], stopped: Apply | None, gate_ms: int
) -> _Phases:
    """The write and the verification, in the order the module docstring fixes."""
    if not request.apply:
        return _Phases(None, _silent("dry_run"))
    if stopped is not None:
        return _Phases(stopped, _silent("no_changes_to_verify"), gate_ms)

    # Nothing to write, so no command is asked about or refused.
    if not changes:
        return _Phases(_write(request, changes)[0], _silent("no_changes_to_verify"), gate_ms)

    permitted = verifier.resolve(
        request.root,
        mode=request.mode,
        config_dir=request.config_dir,
        cli_commands=request.cli_commands,
        repo_commands=request.config.verify.commands,
        ask=request.ask,
    )
    if isinstance(permitted, verifier.Refused):
        applied, write_ms = _write(request, changes)
        return _Phases(applied, _after(applied, "policy_refused"), gate_ms + write_ms)
    if not permitted.commands:
        applied, write_ms = _write(request, changes)
        return _Phases(applied, _after(applied, "no_verify_commands"), gate_ms + write_ms)
    return _checked(request, changes, permitted.commands, gate_ms)


def _checked(
    request: Request,
    changes: Sequence[Change],
    commands: tuple[verifier.Command, ...],
    gate_ms: int,
) -> _Phases:
    """The branch with a verification: baseline, write, compile, after."""
    with TemporaryDirectory(prefix="obelize-verify-", ignore_cleanup_errors=True) as scratch:
        before = Path(scratch) / run_dir.BASELINE
        after = Path(scratch) / run_dir.PHASE_AFTER
        before.mkdir()
        after.mkdir()

        verifying = time.monotonic()
        baseline = verdicts.phase(
            verifier.run(
                request.root,
                commands,
                timeout_s=request.config.verify.timeout_s,
                environ=request.environ,
                junit_dir=before if request.config.verify.junit else None,
            )
        )
        gated = verdicts.gate(baseline)
        verify_ms = _ms(verifying)

        applied, write_ms = _write(request, changes)
        produced = {run_dir.BASELINE: reports(before), run_dir.PHASE_AFTER: reports(after)}
        if not applied.written:
            unwritten = VerifyResult(
                status="not_run", reason="no_changes_to_verify", baseline=baseline
            )
            return _Phases(applied, _record(unwritten, produced), gate_ms + write_ms, verify_ms)

        if gated is not None:
            return _Phases(applied, _record(gated, produced), gate_ms + write_ms, verify_ms)

        resuming = time.monotonic()
        result = _after_the_patch(request, applied, commands, baseline, after)
        produced[run_dir.PHASE_AFTER] = reports(after)
        return _Phases(
            applied, _record(result, produced), gate_ms + write_ms, verify_ms + _ms(resuming)
        )


def _after_the_patch(
    request: Request,
    applied: Apply,
    commands: tuple[verifier.Command, ...],
    baseline: VerifyPhase,
    junit: Path,
) -> VerifyResult:
    """The compile gate, then the commands: a suite over a tree that does not import is noise."""
    broken = cheap.uncompilable(request.root, [row.path for row in applied.written])
    if broken:
        return VerifyResult(
            status="fail", reason="changed_file_does_not_compile", baseline=baseline
        )
    return verdicts.decide(
        verdicts.phase(
            verifier.run(
                request.root,
                commands,
                timeout_s=request.config.verify.timeout_s,
                environ=request.environ,
                junit_dir=junit if request.config.verify.junit else None,
            )
        ),
        baseline=baseline,
    )


def _write(request: Request, changes: Sequence[Change]) -> tuple[Apply, int]:
    """The write itself, timed; `fsutil.apply` asks both gates again."""
    writing = time.monotonic()
    applied = fsutil.apply(request.root, list(changes), allow_dirty=request.config.allow_dirty)
    return applied, _ms(writing)


def _record(result: VerifyResult, produced: Mapping[str, dict[str, bytes]]) -> run_dir.Verified:
    return run_dir.verification(
        result,
        after_junit=produced[run_dir.PHASE_AFTER],
        baseline_junit=produced[run_dir.BASELINE],
    )


def _silent(reason: VerifyReason) -> run_dir.Verified:
    """A verification that did not happen, and why."""
    return run_dir.verification(VerifyResult(status="not_run", reason=reason))


def _after(applied: Apply, reason: VerifyReason) -> run_dir.Verified:
    """`_silent`, except an apply that wrote no file is `no_changes_to_verify` whatever `reason`."""
    return _silent(reason if applied.written else "no_changes_to_verify")


def _exit(phases: _Phases, *, outstanding: bool, idle: bool) -> ExitCode:
    """`docs/CLI.md`'s exit precedence: 5, 3, 6, 4, 0 (7 left earlier, via `obelize.cli`).

    `idle`: no pack applies, so writing nothing is the whole job and not a withheld one.
    """
    if phases.applied is not None and phases.applied.blocked:
        return 5
    code = verdicts.exit_code(phases.verified.record)
    if code:
        return code
    if phases.applied is not None and ((not phases.applied.written and not idle) or outstanding):
        return 4
    return 0


def _ms(since: float) -> int:
    return int((time.monotonic() - since) * 1000)


__all__ = ["Outcome", "Request", "context", "run"]
