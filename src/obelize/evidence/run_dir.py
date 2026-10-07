"""The run folder (`docs/RUN_FOLDER.md`) and its crash-safe write order.

Every artefact precedes `run.json` and `.obelize/latest` follows it, so `latest` only names a
complete run. `findings.json` carries no id or clock, so identical scans are byte-identical, and
text goes down as UTF-8 bytes, since Windows text mode would end each line with CRLF.
Nothing is written through a symlink; `verify` and `undo` reach a folder only via `evidence.folder`.
"""

from __future__ import annotations

import json
import platform as platform_module
import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from obelize import __version__
from obelize.evidence import patch as patching
from obelize.evidence import report
from obelize.evidence.folder import RunFolder
from obelize.fsutil import Change, sha256
from obelize.models import (
    RUN_ID_PATTERN,
    CommandRecord,
    ConfigOrigin,
    ExitCode,
    FileEdit,
    PackRef,
    PlanDocument,
    RunConfig,
    RunCounts,
    RunJournal,
    RunLimitation,
    RunPack,
    RunPlatform,
    RunPython,
    RunRecord,
    RunRefusal,
    RunTimings,
    UndoRecord,
    VerifyPhaseRecord,
    VerifyRecord,
    Withheld,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping, Sequence

    from obelize.fsutil import Apply
    from obelize.gitutil import State
    from obelize.models import (
        Config,
        RefusalCode,
        RunMode,
        RunModel,
        VerifyPhase,
        VerifyResult,
    )
    from obelize.packs.loader import LoadedPack
    from obelize.scan.runner import Scan
    from obelize.scan.runtime import Blocked
    from obelize.transforms.codemod import Run

# Excluded from every scan before any user config, or a scan would report the last one's report.
HOME = ".obelize"

# Run folders, and the pointer to the most recent complete one.
RUNS = "runs"
LATEST = "latest"

# Holds `*`, so `git add -A` never takes a run folder's source copies and command output.
IGNORE = ".gitignore"

# UTC ISO 8601 basic: no colon (illegal on Windows), and it sorts chronologically.
STAMP = "%Y%m%dT%H%M%SZ"

# `timings` use extended ISO 8601: never a filename, so colons are fine.
INSTANT = "%Y-%m-%dT%H:%M:%SZ"

# Separates runs started in the same second; not a secret.
ENTROPY_BYTES = 4

# `snapshots/{before,after}/<sha256>`: named by the hashes `file_edits[]` records.
SNAPSHOTS = "snapshots"
BEFORE = "before"
AFTER = "after"

# One directory per phase: runner numbering restarts at 1 per call, so names would collide.
VERIFY = "verify"
BASELINE = "baseline"
PHASE_AFTER = "after"

# Written into the reverted run's folder; undo creates no run of its own.
UNDO = "undo.json"

# An apply's planned rows, written before it writes; removed once `run.json` is down.
JOURNAL = "journal.json"

# The verification record without its logs.
VERIFY_INDEX = "verify.json"

# `refused[].detail` per code, one actionable sentence. `tree_dirty` gets a path count, never the
# paths: they are the user's own uncommitted work.
REFUSALS: dict[RefusalCode, str] = {
    "file_changed_since_read": "the file changed after obelize read it; run the command again",
    "missing": "the file was deleted after obelize read it",
    "not_a_file": "not a regular file when obelize went to write it",
    "outside_root": "the path resolves outside the repository",
    "symlink": "the path is a symbolic link, and obelize does not write through links",
    "tree_dirty": "commit or stash them, or pass --allow-dirty",
    "tree_unknown": (
        "git could not report whether the working tree has uncommitted changes; "
        "run git status to see why, or pass --allow-dirty"
    ),
    "unreadable": "the file could not be read or written",
}


class EvidenceError(Exception):
    """The run folder could not be written; the message says what to do."""


@dataclass(frozen=True, slots=True)
class Written:
    run_id: str
    # Repository-relative; the CLI prints it under `--repo` as typed.
    relative: str
    directory: Path


@dataclass(frozen=True, slots=True)
class Loaded:
    """A run folder read back by `verify` or `undo`."""

    record: RunRecord
    # Opens no directory through a link.
    folder: RunFolder
    relative: str


@dataclass(frozen=True, slots=True)
class Planned:
    """`plan.json`, `patch.diff`, and the `changes` both derive from (snapshotted and applied)."""

    document: PlanDocument
    patch: bytes
    changes: tuple[Change, ...] = ()


@dataclass(frozen=True, slots=True)
class Verified:
    """The record plus its run-folder-relative log and junit files, kept out of `run.json`."""

    record: VerifyRecord
    files: tuple[tuple[str, bytes], ...] = ()

    @property
    def ran(self) -> bool:
        """Whether any command ran, so whether `verify/` is written; `not_run` has no commands."""
        baseline = self.record.baseline
        return bool(self.record.commands or (baseline is not None and baseline.commands))


@dataclass(frozen=True, slots=True)
class Artefacts:
    """What a plan or apply adds to a scan's artefacts."""

    plan: str
    patch: bytes
    verify: Verified
    snapshots: tuple[tuple[str, bytes], ...] = ()
    # Run-folder-relative `model/model.json` and `model/proposals-<n>.json` per consultation;
    # empty when no provider is configured.
    model: tuple[tuple[str, bytes], ...] = ()


def now() -> datetime:
    """UTC, to the second; a seam for tests."""
    return datetime.now(tz=UTC).replace(microsecond=0)


def new_id(when: datetime | None = None, suffix: str | None = None) -> str:
    moment = now() if when is None else when
    tail = secrets.token_hex(ENTROPY_BYTES) if suffix is None else suffix
    return f"{moment.strftime(STAMP)}-{tail}"


def instant(when: datetime) -> str:
    return when.strftime(INSTANT)


def compose(
    *,
    run_id: str,
    scan: Scan,
    packs: Sequence[Used],
    config: Config,
    source: ConfigOrigin,
    git: State,
    argv: tuple[str, ...],
    started: datetime,
    finished: datetime,
    total_ms: int,
    scan_ms: int,
    exit_code: ExitCode = 0,
) -> RunRecord:
    """A scan's `run.json` record.

    `total_ms` is measured because the timestamps are to the second. A failing scan never gets here
    (bad packs and usage errors stop before a folder exists), so `exit_code` is 0.
    """
    return RunRecord(
        run_id=run_id,
        obelize_version=__version__,
        mode="scan",
        exit_code=exit_code,
        argv=argv,
        python=_python(),
        platform=_platform(),
        git_sha=git.sha,
        git_branch=git.branch,
        git_dirty=git.dirty,
        packs=_packs(packs),
        config=_config(config, source),
        counts=RunCounts(**scan.counts.model_dump()),
        withheld=tuple(Withheld.of(finding) for finding in report.withheld_rows(scan.findings)),
        limitations=_limitations(scan),
        timings=RunTimings(
            started_at=instant(started),
            finished_at=instant(finished),
            total_ms=total_ms,
            scan_ms=scan_ms,
        ),
    )


def planned(
    run: Run, packs: Sequence[LoadedPack], proposals: Mapping[str, tuple[int, ...]] | None = None
) -> Planned:
    """What one driver run would write, built in one pass so the patch, hunks and snapshots agree.

    `proposals` maps a path to model proposal numbers: a `FileEdit` needs a rule or a proposal.
    """
    numbers = proposals or {}
    changes = tuple(
        Change(path=outcome.path, before=outcome.before, after=outcome.after)
        for outcome in run.written
    )
    patches = patching.diff(changes)
    source = {change.path: change for change in changes}
    rules = {
        outcome.path: tuple(
            sorted({row.rule_id for row in outcome.edits if row.status == "auto" and row.rule_id})
        )
        for outcome in run.written
    }
    document = PlanDocument(
        obelize_version=__version__,
        packs=refs(packs),
        files=tuple(
            FileEdit(
                path=one.path,
                before_sha256=sha256(source[one.path].before),
                after_sha256=sha256(source[one.path].after),
                hunks=one.hunks,
                rules=rules[one.path],
                proposals=numbers.get(one.path, ()),
            )
            for one in patches
        ),
        edits=tuple(sorted(run.edits, key=lambda row: (row.path, row.line))),
    )
    return Planned(
        document=document,
        patch=patching.render(patches),
        changes=tuple(sorted(changes, key=lambda change: change.path)),
    )


def verification(
    result: VerifyResult,
    *,
    after_junit: Mapping[str, bytes] | None = None,
    baseline_junit: Mapping[str, bytes] | None = None,
) -> Verified:
    """The folder's verification; junit maps stay per phase, as runner names collide across them."""
    files: list[tuple[str, bytes]] = []
    baseline = (
        None
        if result.baseline is None
        else _phase(result.baseline, BASELINE, baseline_junit or {}, files)
    )
    after = _phase(result, PHASE_AFTER, after_junit or {}, files)
    return Verified(
        record=VerifyRecord(
            status=after.status,
            reason=after.reason,
            commands=after.commands,
            baseline=baseline,
        ),
        files=tuple(files),
    )


def artefacts(
    plan: Planned,
    verified: Verified,
    applied: Apply | None = None,
    model: Sequence[tuple[str, bytes]] = (),
) -> Artefacts:
    """What a plan or apply adds; a dry run (`applied is None`) has nothing to snapshot."""
    return Artefacts(
        plan=plan.document.model_dump_json(indent=2) + "\n",
        patch=plan.patch,
        verify=verified,
        snapshots=_snapshots(plan, applied),
        model=tuple(model),
    )


def compose_fix(
    *,
    run_id: str,
    scan: Scan,
    run: Run,
    plan: Planned,
    verified: Verified,
    packs: Sequence[Used],
    config: Config,
    source: ConfigOrigin,
    git: State,
    argv: tuple[str, ...],
    applied: Apply | None = None,
    model: RunModel | None = None,
    exit_code: ExitCode = 0,
    started: datetime,
    finished: datetime,
    total_ms: int,
    scan_ms: int,
    plan_ms: int,
    apply_ms: int | None = None,
    verify_ms: int | None = None,
    model_ms: int | None = None,
) -> RunRecord:
    """A plan's or apply's `run.json` record.

    Any run with an `Apply` is an apply, even one refused over a dirty tree. Phase clocks are passed
    in (this runs once, at the end); `RunRecord` rejects a set that does not fit the mode.
    """
    mode: RunMode = "plan" if applied is None else "apply"
    edits = _written(plan, applied)
    return RunRecord(
        run_id=run_id,
        obelize_version=__version__,
        mode=mode,
        exit_code=exit_code,
        argv=argv,
        python=_python(),
        platform=_platform(),
        git_sha=git.sha,
        git_branch=git.branch,
        git_dirty=git.dirty,
        packs=_packs(packs),
        config=_config(config, source),
        counts=_fix_counts(scan, run),
        file_edits=edits,
        refused=_refused(applied),
        idempotent=None if mode == "plan" else not edits,
        withheld=tuple(Withheld.of(finding) for finding in report.withheld_rows(run.findings)),
        verify=verified.record,
        model=model,
        limitations=_limitations(scan),
        timings=RunTimings(
            started_at=instant(started),
            finished_at=instant(finished),
            total_ms=total_ms,
            scan_ms=scan_ms,
            plan_ms=plan_ms,
            apply_ms=apply_ms,
            verify_ms=verify_ms,
            model_ms=model_ms,
        ),
    )


def journal(root: Path, run_id: str, plan: Planned) -> None:
    """Before any write: create the folder, copy every planned original, write the journal.

    So an interrupted apply leaves what `undo` needs, and a bad folder fails before a file changes.
    """
    home = _home(root)
    runs = _directory(home / RUNS)
    folder = runs / run_id
    rows = RunJournal(run_id=run_id, file_edits=plan.document.files)
    try:
        folder.mkdir(exist_ok=False)
        for change in plan.changes:
            _artefact(folder, snapshot(sha256(change.before)), change.before)
        (folder / JOURNAL).write_bytes(rows.model_dump_json(indent=2).encode("utf-8") + b"\n")
    except OSError as error:
        raise EvidenceError(
            f"the run folder {HOME}/{RUNS}/{run_id} could not be written: {error.strerror}. "
            f"No file in the repository was changed."
        ) from error


def write(
    root: Path,
    record: RunRecord,
    findings: str,
    packs: Sequence[LoadedPack],
    document: str,
    fix: Artefacts | None = None,
    *,
    journaled: bool = False,
) -> Written:
    """Write the artefacts, then `run.json`, then `latest`.

    `findings` is the exact `--json` output (the spec requires identical bytes). `fix` must match
    the mode, checked before anything is created. A `journaled` folder exists already; its unused
    snapshots and journal are removed after `run.json`.
    """
    _agree(record, fix)
    home = _home(root)
    runs = _directory(home / RUNS)
    folder = runs / record.run_id
    try:
        folder.mkdir(parents=True, exist_ok=journaled)
        (folder / "findings.json").write_bytes(findings.encode("utf-8"))
        for pack in packs:
            where = f"packs/{pack.pack.id}"
            _artefact(folder, f"{where}/pack.yaml", pack.data)
            _artefact(folder, f"{where}/pack.sha256", f"{pack.sha256}\n".encode())
        (folder / "REPORT.md").write_bytes(document.encode("utf-8"))
        if fix is not None:
            (folder / "plan.json").write_bytes(fix.plan.encode("utf-8"))
            (folder / "patch.diff").write_bytes(fix.patch)
            for name, data in (*fix.snapshots, *fix.verify.files, *fix.model):
                _artefact(folder, name, data)
            if fix.verify.ran:
                _artefact(
                    folder,
                    f"{VERIFY}/{VERIFY_INDEX}",
                    fix.verify.record.model_dump_json(indent=2).encode("utf-8") + b"\n",
                )
        (folder / "run.json").write_bytes(record.model_dump_json(indent=2).encode("utf-8") + b"\n")
        if journaled:
            _pruned(folder, {name for name, _data in fix.snapshots} if fix else set())
            (folder / JOURNAL).unlink()
        _pointer(home / LATEST, record.run_id)
    except OSError as error:
        raise EvidenceError(
            f"the run folder under {HOME}/{RUNS}/{record.run_id} could not be written: "
            f"{error.strerror}. The run itself completed; nothing was recorded."
        ) from error
    return Written(
        run_id=record.run_id,
        relative=f"{HOME}/{RUNS}/{record.run_id}",
        directory=folder,
    )


def _pruned(folder: Path, kept: set[str]) -> None:
    """Delete snapshot copies not in `kept`, then any directory left empty."""
    for half in (BEFORE, AFTER):
        directory = folder / SNAPSHOTS / half
        for path in sorted(directory.iterdir()) if directory.is_dir() else ():
            if f"{SNAPSHOTS}/{half}/{path.name}" not in kept:
                path.unlink()
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    if (folder / SNAPSHOTS).is_dir() and not any((folder / SNAPSHOTS).iterdir()):
        (folder / SNAPSHOTS).rmdir()


@dataclass(frozen=True, slots=True)
class Interrupted:
    """An apply that stopped after its journal and before its record."""

    file_edits: tuple[FileEdit, ...]
    folder: RunFolder
    relative: str


def interrupted(root: Path, run_id: str) -> Interrupted | None:
    """The journal of a run with no `run.json`, for `undo`; `None` if absent or unreadable."""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        return None
    folder = RunFolder(root, HOME, RUNS, run_id)
    try:
        rows = RunJournal.model_validate_json(folder.read(JOURNAL))
    except (OSError, ValueError):
        return None
    relative = f"{HOME}/{RUNS}/{run_id}"
    return Interrupted(file_edits=rows.file_edits, folder=folder, relative=relative)


def load(root: Path, run_id: str) -> Loaded:
    """Read back a run folder's `run.json`.

    The id must match `RUN_ID_PATTERN` before it touches a path, so `--run ../../etc` fails by
    shape. Missing, unreadable and invalid each get their own message.
    """
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise EvidenceError(
            f"{run_id!r} is not a run id of the form 20260917T142530Z-3f9a1c72. "
            f"{HOME}/{LATEST} holds the most recent one."
        )
    if not (root / HOME / RUNS / run_id).is_dir():
        raise EvidenceError(f"there is no run {run_id} under {HOME}/{RUNS} of this repository")
    folder = RunFolder(root, HOME, RUNS, run_id)
    try:
        data = folder.read("run.json").decode("utf-8")
    except OSError as error:
        raise EvidenceError(
            f"{HOME}/{RUNS}/{run_id}/run.json cannot be read: {error.strerror}"
        ) from error
    try:
        record = RunRecord.model_validate(json.loads(data))
    except (ValueError, TypeError) as error:
        raise EvidenceError(
            f"{HOME}/{RUNS}/{run_id}/run.json is not a run record this version of obelize "
            f"can read: {error}"
        ) from error
    return Loaded(record=record, folder=folder, relative=f"{HOME}/{RUNS}/{run_id}")


def snapshot(digest: str, half: str = BEFORE) -> str:
    """A snapshot's path in the run folder, spelled once for the writer and both readers."""
    return f"{SNAPSHOTS}/{half}/{digest}"


def reverified(record: RunRecord, verified: Verified, *, exit_code: ExitCode, ms: int) -> RunRecord:
    """The record with a new verification in place of the first, rebuilt so it is re-validated.

    `argv` and the rest stay the run's own. The baseline is dropped: there is no pre-patch tree to
    re-measure and `VerifyResult` forbids one on the `not_run` a re-verification records;
    `verify/baseline/` keeps its output.
    """
    data = record.model_dump()
    data["verify"] = verified.record.model_dump()
    data["exit_code"] = exit_code
    data["timings"]["verify_ms"] = None if verified.record.status == "not_run" else ms
    return RunRecord.model_validate(data)


def rewrite(loaded: Loaded, record: RunRecord, verified: Verified, note: str | None = None) -> None:
    """Replace the verification half of an existing folder: artefacts first, as in `write`.

    `latest` is untouched (no run is created). `verify/after/` is emptied so no stale log reads as
    the new phase's; `verify/baseline/` is kept. `verify/verify.json` is rewritten even when nothing
    ran, to match `run.json`. `note` is the superseded report, or `None` to keep it.
    """
    folder = loaded.folder
    try:
        folder.empty(f"{VERIFY}/{PHASE_AFTER}")
        for name, data in verified.files:
            folder.write(name, data)
        folder.write(
            f"{VERIFY}/{VERIFY_INDEX}",
            verified.record.model_dump_json(indent=2).encode("utf-8") + b"\n",
        )
        if note is not None:
            folder.write("REPORT.md", note.encode("utf-8"))
        folder.write("run.json", (record.model_dump_json(indent=2) + "\n").encode("utf-8"))
    except OSError as error:
        raise EvidenceError(
            f"the verification could not be recorded in {loaded.relative}: {error.strerror}. "
            f"The commands ran, but their results were not saved."
        ) from error


def undone(folder: RunFolder, relative: str, record: UndoRecord) -> str:
    """Write `undo.json` into the reverted run's folder; return its repository-relative path."""
    try:
        folder.write(UNDO, (record.model_dump_json(indent=2) + "\n").encode("utf-8"))
    except OSError as error:
        raise EvidenceError(
            f"{relative}/{UNDO} could not be written: {error.strerror}. The files were "
            f"put back, but what happened to each was not saved."
        ) from error
    return f"{relative}/{UNDO}"


def _agree(record: RunRecord, fix: Artefacts | None) -> None:
    """Check the index against the artefacts before anything is written.

    Only a fix has a plan; snapshot names equal the `file_edits[]` hashes (an unindexed one is
    unreachable); `verify/verify.json` equals the embedded verification; model files match `model`.
    """
    if (record.mode == "scan") != (fix is None):
        raise EvidenceError(
            f"a {record.mode!r} run writes "
            f"{'no plan and no patch' if record.mode == 'scan' else 'a plan and a patch'}, "
            f"and it was handed {'some' if fix is not None else 'none'}"
        )
    if fix is None:
        return
    named = {name for name, _ in fix.snapshots}
    expected = {f"{SNAPSHOTS}/{BEFORE}/{row.before_sha256}" for row in record.file_edits} | {
        f"{SNAPSHOTS}/{AFTER}/{row.after_sha256}" for row in record.file_edits
    }
    if named != expected:
        raise EvidenceError(
            f"the snapshots and `file_edits` describe different files: "
            f"{sorted(named ^ expected)} is in one and not the other"
        )
    if fix.verify.record != record.verify:
        raise EvidenceError(
            "`verify/verify.json` and `run.json`'s `verify` are one verification written "
            "twice, and these two are not the same one"
        )
    if bool(fix.model) != (record.model is not None):
        raise EvidenceError(
            f"the index records {'a' if record.model is not None else 'no'} model and the "
            f"folder was handed {len(fix.model)} file(s) for one"
        )


def _artefact(folder: Path, relative: str, data: bytes) -> None:
    destination = folder / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def _phase(
    phase: VerifyPhase, directory: str, junit: Mapping[str, bytes], files: list[tuple[str, bytes]]
) -> VerifyPhaseRecord:
    """One phase's rows, appending their files; log names repeat the runner's 1-based numbering."""
    rows = []
    for index, result in enumerate(phase.commands, start=1):
        log: str | None = None
        if result.output:
            log = f"{VERIFY}/{directory}/{index}.log"
            # The runner decoded with surrogateescape: this restores the exact bytes printed.
            files.append((log, result.output.encode("utf-8", "surrogateescape")))
        produced: str | None = None
        if result.junit is not None:
            data = junit.get(result.junit)
            if data is None:
                raise EvidenceError(
                    f"{result.command!r} recorded the junit report {result.junit!r}, but its "
                    f"bytes were not passed in"
                )
            produced = f"{VERIFY}/{directory}/{result.junit}"
            files.append((produced, data))
        rows.append(CommandRecord.of(result, log=log, junit=produced))
    return VerifyPhaseRecord(status=phase.status, reason=phase.reason, commands=tuple(rows))


def _snapshots(plan: Planned, applied: Apply | None) -> tuple[tuple[str, bytes], ...]:
    """`snapshots/before/` and `snapshots/after/` for written files; none on a dry run.

    fsutil's hashes match the plan's bytes because `fsutil.apply` refuses a drifted file.
    """
    if applied is None:
        return ()
    source = {change.path: change for change in plan.changes}
    rows: dict[str, bytes] = {}
    for row in applied.written:
        change = source[row.path]
        rows[f"{SNAPSHOTS}/{BEFORE}/{row.before_sha256}"] = change.before
        rows[f"{SNAPSHOTS}/{AFTER}/{row.after_sha256}"] = change.after
    return tuple(sorted(rows.items()))


def _written(plan: Planned, applied: Apply | None) -> tuple[FileEdit, ...]:
    """The plan's rows that reached disk, in plan order; `hunks` and `rules` exist only there."""
    if applied is None:
        return ()
    done = {row.path for row in applied.written}
    return tuple(row for row in plan.document.files if row.path in done)


def _refused(applied: Apply | None) -> tuple[RunRefusal, ...]:
    """What the apply planned and did not write, and why.

    A dirty or unknown tree refuses the whole apply before any file opens, so it stands alone.
    """
    if applied is None:
        return ()
    if applied.unknown:
        return (RunRefusal(code="tree_unknown", detail=REFUSALS["tree_unknown"]),)
    if applied.dirty:
        count = len(applied.dirty)
        detail = (
            f"git does not track {count} file(s) this run would edit, so git diff could not "
            f"show the change; {report.UNTRACKED}"
            if applied.untracked
            else f"{count} path(s) in the working tree have uncommitted changes, and git diff "
            f"should show only the migration; {REFUSALS['tree_dirty']}"
        )
        return (RunRefusal(code="tree_dirty", detail=detail),)
    return tuple(
        sorted(
            (
                RunRefusal(code=row.reason, path=row.path, detail=REFUSALS[row.reason])
                for row in applied.refused
            ),
            key=lambda row: ((row.path or ""), row.code),
        )
    )


def _fix_counts(scan: Scan, run: Run) -> RunCounts:
    """A fix run's counts: file counts from the scan, the rest from what the driver left.

    `auto` is the driver's `eligible` (atomicity already demoted every row of a withheld file);
    `findings` is the driver's, since the manifest pin check can grade one manifest declaration
    twice.
    """
    revised = run.findings
    split = Counter(finding.scan_status for finding in revised)
    return RunCounts(
        files_selected=scan.counts.files_selected,
        files_parsed=scan.counts.files_parsed,
        findings=len(revised),
        # Explicit: `RunRecord` rejects a fix that reports `eligible` rows.
        eligible=0,
        auto=split["eligible"],
        needs_review=split["needs_review"],
        unsupported=split["unsupported"],
        not_a_usage=split["not_a_usage"],
        warnings=sum(1 for row in run.edits if row.warnings),
    )


def _python() -> RunPython:
    """Version and implementation, deliberately not the interpreter's path."""
    return RunPython(
        version=platform_module.python_version(),
        implementation=platform_module.python_implementation(),
    )


def _platform() -> RunPlatform:
    return RunPlatform(
        system=platform_module.system(),
        release=platform_module.release(),
        machine=platform_module.machine(),
    )


@dataclass(frozen=True, slots=True)
class Used:
    """A pack a run used, and the declaration that stopped it, if the repository did."""

    loaded: LoadedPack
    blocked: Blocked | None = None


def refs(packs: Sequence[LoadedPack]) -> tuple[PackRef, ...]:
    """The packs as the documents name them, in id order."""
    return tuple(
        PackRef(id=pack.pack.id, version=pack.pack.pack_version, sha256=pack.sha256)
        for pack in sorted(packs, key=lambda pack: pack.pack.id)
    )


def _packs(packs: Sequence[Used]) -> tuple[RunPack, ...]:
    return tuple(
        RunPack(
            id=used.loaded.pack.id,
            pack_version=used.loaded.pack.pack_version,
            sha256=used.loaded.sha256,
            source="bundled" if used.loaded.bundled else "file",
            blocked=None if used.blocked is None else used.blocked.reason,
        )
        for used in sorted(packs, key=lambda used: used.loaded.pack.id)
    )


def _config(config: Config, source: ConfigOrigin) -> RunConfig:
    return RunConfig(
        source=source,
        include=config.include,
        exclude=tuple(config.exclude),
        max_file_bytes=config.max_file_bytes,
    )


def _home(root: Path) -> Path:
    """`.obelize/`, given its ignore file unless something is at that name already."""
    home = _directory(root / HOME)
    try:
        RunFolder(root, HOME).create(IGNORE, b"*\n")
    except OSError as error:
        raise EvidenceError(f"{HOME}/{IGNORE} could not be written: {error.strerror}") from error
    return home


def _directory(path: Path) -> Path:
    if path.is_symlink() or path.is_junction():
        raise EvidenceError(
            f"{path.name} is a symbolic link or a junction, and obelize does not write through "
            f"links. Remove it or choose another --repo."
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise EvidenceError(
            f"{HOME} could not be created under the repository root: {error.strerror}"
        ) from error
    return path


def _pointer(path: Path, run_id: str) -> None:
    """`.obelize/latest`: the id plus a newline, so `$(cat ...)` needs no trim. Never a link."""
    if path.is_symlink() or path.is_junction():
        raise EvidenceError(
            f"{HOME}/{LATEST} is a symbolic link or a junction. Remove it and run again; obelize "
            f"writes it as a regular file."
        )
    path.write_bytes(f"{run_id}\n".encode())


def _limitations(scan: Scan) -> tuple[RunLimitation, ...]:
    """Walker skips and reader refusals, as one sorted `limitations[]`.

    An unusable name is no repository path, so its row quotes the name in the detail instead.
    """
    rows = [
        RunLimitation(code=row.reason, detail=f"{row.path}: {row.detail}")
        if row.reason == "unusable_name"
        else RunLimitation(code=row.reason, path=row.path, detail=row.detail)
        for row in scan.skipped
    ] + [RunLimitation(code=row.code, path=row.path, detail=row.detail) for row in scan.limitations]
    return tuple(
        sorted(rows, key=lambda row: ((row.path or "").encode("utf-8"), row.code, row.detail))
    )


__all__ = [
    "AFTER",
    "BASELINE",
    "BEFORE",
    "ENTROPY_BYTES",
    "HOME",
    "IGNORE",
    "INSTANT",
    "JOURNAL",
    "LATEST",
    "PHASE_AFTER",
    "REFUSALS",
    "RUNS",
    "SNAPSHOTS",
    "STAMP",
    "UNDO",
    "VERIFY",
    "VERIFY_INDEX",
    "Artefacts",
    "EvidenceError",
    "Interrupted",
    "Loaded",
    "Planned",
    "Verified",
    "Written",
    "artefacts",
    "compose",
    "compose_fix",
    "instant",
    "interrupted",
    "journal",
    "load",
    "new_id",
    "now",
    "planned",
    "reverified",
    "rewrite",
    "snapshot",
    "undone",
    "verification",
    "write",
]
