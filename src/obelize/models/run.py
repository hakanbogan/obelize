"""The run folder's documents: plan, run, model, proposals and undo."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import AfterValidator, Field, model_validator

from obelize.models.fields import (
    RelativePath,
    Sha256,
    _check_caused_by,
    _Frozen,
    schema_hint,
    sorted_unique,
)
from obelize.models.scan import Edit, EditProposal, Finding, PackRef, ScanCounts
from obelize.models.verify import VerifyRecord
from obelize.models.vocabulary import (
    FIX_MODES,
    BailCode,
    BlockedReason,
    ConfigOrigin,
    ConsultSkip,
    ExitCode,
    FixerId,
    GuardRefusal,
    LimitationCode,
    PackOrigin,
    ProposalOutcome,
    ProviderFailure,
    ProviderName,
    RefusalCode,
    RunMode,
    UndoOutcome,
    UndoSkip,
)


class FileEdit(_Frozen):
    """One file whose bytes a run would change (`plan.json`) or changed (`run.json`)."""

    # One shape for both documents, so a dry run and an apply compare row for row.
    path: RelativePath
    before_sha256: Sha256
    after_sha256: Sha256
    hunks: int = Field(ge=1)
    rules: tuple[str, ...]
    # The `model/proposals-<n>.json` behind this file, as `rules` traces a pack edit; at most one
    # per file per run.
    proposals: tuple[int, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> FileEdit:
        if self.before_sha256 == self.after_sha256:
            raise ValueError(
                f"{self.path} is recorded as edited and its bytes did not change; a file "
                f"nothing changed is not an edit, it is the absence of one"
            )
        if not self.rules and not self.proposals:
            raise ValueError(
                f"{self.path} was rewritten by nothing; an applied hunk with neither a rule "
                f"nor a proposal behind it is a hunk no reviewer can trace to anything"
            )
        if self.rules and self.proposals:
            raise ValueError(
                f"{self.path} names both a pack rule and a model proposal; a file a rule "
                f"rewrote has no withheld finding, so nothing in it was asked about"
            )
        if any(number < 1 for number in self.proposals):
            raise ValueError(f"proposals are numbered from 1, got {list(self.proposals)}")
        sorted_unique(self.rules, "rules")
        sorted_unique(self.proposals, "proposals")
        return self


class PlanDocument(_Frozen):
    """The `plan.json` document: what a run would write, whether or not it wrote it."""

    # Nothing time-derived and no counts: unlike findings.json it never leaves a run folder,
    # where run.json holds both.
    obelize_version: str
    packs: tuple[PackRef, ...] = ()
    files: tuple[FileEdit, ...] = ()
    edits: tuple[Edit, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> PlanDocument:
        sorted_unique(tuple(pack.id for pack in self.packs), "packs")
        paths = [row.path for row in self.files]
        if paths != sorted(paths):
            raise ValueError("the files a run would write are written in path order")
        if len(set(paths)) != len(paths):
            raise ValueError("one file is one row; two rows for one path is two answers")
        keys = [(row.path, row.line) for row in self.edits]
        if keys != sorted(keys):
            raise ValueError("edits are written in document order; sort before emitting")
        return self


# Public: `verify --run <id>` and `undo --run <id>` check the argument before joining it onto a
# path, so an id of any other shape never becomes a directory name (TM-1).
RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")

_INSTANT = re.compile(r"^[0-9]{4}(-[0-9]{2}){2}T[0-9]{2}(:[0-9]{2}){2}Z$")


def _run_id(value: str) -> str:
    """The folder name: sorts chronologically, and has no colon, which Windows file names forbid."""
    if not RUN_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{value!r} is not a run id of the form 20260917T142530Z-3f9a1c72")
    return value


def _instant(value: str) -> str:
    if not _INSTANT.fullmatch(value):
        raise ValueError(
            f"{value!r} is not an ISO 8601 UTC timestamp of the form 2026-09-18T09:14:07Z"
        )
    return value


RunId = Annotated[str, AfterValidator(_run_id), schema_hint(pattern=RUN_ID_PATTERN.pattern)]
Instant = Annotated[str, AfterValidator(_instant), schema_hint(pattern=_INSTANT.pattern)]


class RunPython(_Frozen):
    """The interpreter that ran, deliberately without its path, which would name the machine."""

    version: str
    implementation: str


class RunPlatform(_Frozen):
    """The operating system and machine the run used, as Python's `platform` module reports them."""

    system: str
    release: str
    machine: str


class RunPlugin(_Frozen):
    """A plugin a pack required and the run loaded: where it came from, and what was installed."""

    name: str
    distribution: str
    version: str
    # The hash of the distribution's `RECORD`, which lists the hash of every file it installed;
    # `None` where the installer left none (an editable install).
    record_sha256: Sha256 | None = None


class RunFixerFile(_Frozen):
    """One file a fixer's tool was run over: the bytes it was given, the bytes it printed and the
    lines it changed, whether or not the proof kept them."""

    path: RelativePath
    before_sha256: Sha256
    after_sha256: Sha256
    lines: int = Field(ge=0)


class RunFixer(_Frozen):
    """A maintained tool a pack's `external_fixer` ran: the release it printed, how it was started
    (`{name}` is the file's name) and the files it was run over, in scan order."""

    fixer: FixerId
    tool: str
    version: str
    argv: tuple[str, ...]
    files: tuple[RunFixerFile, ...]


class RunPack(_Frozen):
    """The pack a run used: which one, its own version, and its exact bytes."""

    id: str
    pack_version: str
    sha256: Sha256
    source: PackOrigin
    # Why this pack proposed nothing, when the repository ruled its migration out.
    blocked: BlockedReason | None = None
    # The release taken where a declaration names none that rules the pack's newest one out.
    assumed: str | None = None
    # The release `upgrade --from` gave, taken for the one in use where no manifest declares the
    # distribution.
    stated: str | None = None
    # The plugins the pack required, which were loaded in this process.
    plugins: tuple[RunPlugin, ...] = ()
    # The tools the pack's fixers ran, one row each, in id order.
    fixers: tuple[RunFixer, ...] = ()


class RunConfig(_Frozen):
    """The configuration the run used, flags over file, without the exclusions every run applies."""

    source: ConfigOrigin
    include: str
    exclude: tuple[str, ...] = ()
    max_file_bytes: int = Field(gt=0)


class RunCounts(ScanCounts):
    """The finding counts of a run by status, plus its warning count."""

    # A scan reports `eligible`, a plan or apply `auto`, never both (RunRecord checks which).
    auto: int = Field(default=0, ge=0)
    warnings: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check(self) -> RunCounts:
        """Replaces the parent check: the split adds `auto`, which excludes `eligible`."""
        if self.files_parsed > self.files_selected:
            raise ValueError("more files were parsed than were selected")
        split = self.eligible + self.auto + self.needs_review + self.unsupported + self.not_a_usage
        if split != self.findings:
            raise ValueError(f"the status split sums to {split}, and there are {self.findings}")
        if self.eligible and self.auto:
            raise ValueError(
                "a run reports `eligible` or `auto` and never both: one says no scan-time "
                "rule withheld the row and the other says a rule rewrote it"
            )
        return self


class Withheld(_Frozen):
    """One finding the run withheld, with its bail, so `run.json` alone answers why not."""

    path: RelativePath
    line: int = Field(ge=1)
    # Null for the `parse_error` row of an unparsable file, which resolved no usage.
    symbol: str | None = None
    bail: BailCode
    caused_by: tuple[BailCode, ...] | None = None

    @classmethod
    def of(cls, finding: Finding) -> Withheld:
        """The row for a withheld finding; refuses one that withholds nothing."""
        if finding.bail is None:
            raise ValueError(
                f"{finding.path}:{finding.line} is {finding.scan_status!r} and withholds "
                f"nothing, so there is no row for it in `withheld[]`"
            )
        return cls(
            path=finding.path,
            line=finding.line,
            symbol=finding.symbol,
            bail=finding.bail,
            caused_by=finding.caused_by,
        )

    @model_validator(mode="after")
    def _check(self) -> Withheld:
        _check_caused_by(self.bail, self.caused_by, "caused_by")
        return self


class RunLimitation(_Frozen):
    """One thing the run could not look at, so a small count never reads as a clean repository."""

    code: LimitationCode
    path: RelativePath | None = None
    detail: str


class RunRefusal(_Frozen):
    """One file the run planned to write and did not, and the code for why."""

    code: RefusalCode
    path: RelativePath | None = None
    detail: str

    @model_validator(mode="after")
    def _check(self) -> RunRefusal:
        if (self.code in ("tree_dirty", "tree_unknown")) != (self.path is None):
            raise ValueError(
                "`tree_dirty` and `tree_unknown` are the refusals about the repository and "
                "name no path; every other one is about the file it names"
            )
        return self


class RunModel(_Frozen):
    """The `model` object of `run.json`: what a run that consulted a model asked and got back."""

    provider: ProviderName
    # `ModelConfig.host`, never the URL, whose query can carry a credential.
    host: str
    model: str
    # Proposals that came back, not questions asked.
    proposals: int = Field(ge=0)
    # Passed every guard and were written, which needs `--apply` and `--accept-model`.
    accepted: int = Field(ge=0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> RunModel:
        if self.provider == "none":
            raise ValueError(
                "a run with no provider records no model object at all; `none` here would "
                "be a record of a consultation that did not happen"
            )
        if self.accepted > self.proposals:
            raise ValueError(
                f"{self.accepted} of {self.proposals} proposal(s) were written, which is "
                f"more edits than answers"
            )
        return self


class ConsultationSkip(_Frozen):
    """One withheld row a model was not asked about, and the reason why."""

    path: RelativePath
    line: int = Field(ge=1)
    reason: ConsultSkip


class ProposalRecord(_Frozen):
    """The `model/proposals-<n>.json` document: one consultation and what became of it."""

    # Numbered per consultation, not per proposal: an unreachable endpoint still leaves a file.
    index: int = Field(ge=1)
    # The only file the guard lets the proposal edit.
    path: RelativePath
    line: int = Field(ge=1)
    symbol: str | None = None
    # What the deterministic rules refused with; the code is the whole message.
    bail: BailCode
    # The range sent as context, 1-based and inclusive.
    context_start_line: int = Field(ge=1)
    context_end_line: int = Field(ge=1)
    # Of the exact request body, serialised with sorted keys so one question hashes one way.
    prompt_sha256: Sha256
    # Only when `model.log_prompts` is true: a prompt is source code.
    prompt: str | None = None
    provider: ProviderName
    model: str
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    outcome: ProposalOutcome
    failure: ProviderFailure | None = None
    refusal: GuardRefusal | None = None
    # One line from whichever decided; redacted before it is cut, as endpoint text is untrusted.
    detail: str | None = None
    proposal: EditProposal | None = None

    @model_validator(mode="after")
    def _check(self) -> ProposalRecord:
        if self.context_end_line < self.context_start_line:
            raise ValueError(
                f"the context is lines {self.context_start_line}..{self.context_end_line}, "
                f"which is no range at all"
            )
        if (self.failure is not None) != (self.outcome == "unanswered"):
            raise ValueError(
                "`unanswered` is exactly the outcome that carries a `ProviderFailure`, and "
                "every other one is an answer that arrived"
            )
        if (self.refusal is not None) != (self.outcome == "guard_refused"):
            raise ValueError(
                "`guard_refused` is exactly the outcome that carries a `GuardRefusal`; a "
                "proposal that was not refused was not refused for a reason either"
            )
        answered = self.outcome not in ("unanswered", "nothing_proposed")
        if (self.proposal is not None) != answered:
            raise ValueError(
                f"outcome={self.outcome!r} "
                f"{'needs' if answered else 'has'} a proposal "
                f"{'and carries none' if answered else 'and should not'}"
            )
        return self


class ModelDocument(_Frozen):
    """The `model/model.json` index: the run's model summary and the rows never put to a model."""

    # No copy of the proposals: they live in the numbered files and may hold source code.
    obelize_version: str
    summary: RunModel
    # Questions asked, and so the numbered files: `model/proposals-1.json` onward.
    consulted: int = Field(ge=0)
    skipped: tuple[ConsultationSkip, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> ModelDocument:
        if self.summary.proposals > self.consulted:
            raise ValueError(
                f"{self.summary.proposals} proposal(s) came back from {self.consulted} "
                f"question(s); one question is answered at most once"
            )
        keys = [(row.path, row.line) for row in self.skipped]
        if keys != sorted(keys):
            raise ValueError("skipped rows follow the findings, which are in document order")
        return self


class RunTimings(_Frozen):
    """The run's wall-clock times, kept here alone so everything else compares between two runs."""

    started_at: Instant
    finished_at: Instant
    total_ms: int = Field(ge=0)
    scan_ms: int | None = Field(default=None, ge=0)
    plan_ms: int | None = Field(default=None, ge=0)
    apply_ms: int | None = Field(default=None, ge=0)
    verify_ms: int | None = Field(default=None, ge=0)
    # The consultation; present exactly when a model was asked something.
    model_ms: int | None = Field(default=None, ge=0)


class RunJournal(_Frozen):
    """`journal.json`: the plan's file edits, on disk before an apply writes any of them.

    Both copies of each file sit beside it. A finished run replaces it with `run.json`; an
    interrupted one leaves it for `obelize undo`.
    """

    run_id: RunId
    file_edits: tuple[FileEdit, ...]


class RunRecord(_Frozen):
    """The `run.json` document: the index of one run folder."""

    # Fields match docs/RUN_FOLDER.md's table (test_run_folder_contract.py); `mode` decides which
    # may be set, and one that does not apply is null or empty, never absent.
    run_id: RunId
    obelize_version: str
    mode: RunMode
    exit_code: ExitCode
    argv: tuple[str, ...] = ()
    python: RunPython
    platform: RunPlatform
    git_sha: str | None = None
    git_branch: str | None = None
    git_dirty: bool | None = False
    packs: tuple[RunPack, ...] = ()
    config: RunConfig
    counts: RunCounts
    file_edits: tuple[FileEdit, ...] = ()
    refused: tuple[RunRefusal, ...] = ()
    idempotent: bool | None = None
    withheld: tuple[Withheld, ...] = ()
    verify: VerifyRecord | None = None
    model: RunModel | None = None
    limitations: tuple[RunLimitation, ...] = ()
    timings: RunTimings

    @model_validator(mode="after")
    def _check(self) -> RunRecord:
        self._check_order()
        self._check_the_split()
        self._check_the_mode()
        self._check_the_clock()
        return self

    def _check_order(self) -> None:
        sorted_unique(tuple(pack.id for pack in self.packs), "packs")
        keys = [(row.path, row.line) for row in self.withheld]
        if keys != sorted(keys):
            raise ValueError("withheld rows follow the findings, which are in document order")
        limits = [
            ((row.path or "").encode("utf-8"), row.code, row.detail) for row in self.limitations
        ]
        if limits != sorted(limits):
            raise ValueError("limitations are written sorted, so two runs can be compared")
        written = [row.path for row in self.file_edits]
        if written != sorted(written):
            raise ValueError("file_edits is written in path order, the order the writes went in")
        if len(set(written)) != len(written):
            raise ValueError("one file is written once; two rows for one path is two answers")
        refusals = [((row.path or ""), row.code) for row in self.refused]
        if refusals != sorted(refusals):
            raise ValueError("refusals are written sorted, so two runs can be compared")

    def _check_the_split(self) -> None:
        """Which of `eligible` and `auto` this mode is entitled to report."""
        if self.mode in FIX_MODES:
            if self.counts.eligible:
                raise ValueError(
                    f"a {self.mode!r} has run the rules, so its rows are graded `auto` or "
                    f"withheld; `eligible` is what a scan says before any rule was tried"
                )
            return
        if self.counts.auto:
            raise ValueError("a scan has applied no rule, so it can claim no `auto` row")
        if self.counts.warnings:
            raise ValueError("a scan plans no edit, so it can carry no warning")

    def _check_the_mode(self) -> None:
        """What each mode may say about the disk and about the verification."""
        if self.mode == "scan":
            if self.file_edits or self.refused or self.idempotent is not None:
                raise ValueError("a scan writes no file, so it refuses none and changes none")
            if self.verify is not None:
                raise ValueError("a scan has no verification phase")
            if self.model is not None:
                raise ValueError(
                    "a scan plans no edit, so there is nothing for a model to propose one "
                    "for and nothing to consult one about"
                )
            return
        if self.verify is None:
            raise ValueError(
                f"a {self.mode!r} always records a verification, including the runs where "
                f"nothing ran: a missing verdict is an outcome and not an absent field"
            )
        if self.model is not None and self.model.accepted and self.mode != "apply":
            raise ValueError(
                f"a {self.mode!r} run recorded {self.model.accepted} accepted proposal(s), "
                f"and a proposal is accepted by being written"
            )
        proposed = {number for row in self.file_edits for number in row.proposals}
        if proposed and (self.model is None or len(proposed) != self.model.accepted):
            raise ValueError(
                f"{len(proposed)} file edit(s) name a proposal and `model` records "
                f"{None if self.model is None else self.model.accepted} accepted; the two "
                f"count the same writes"
            )
        if self.mode == "plan":
            if self.file_edits or self.refused or self.idempotent is not None:
                raise ValueError("a plan writes nothing; what it would write is plan.json")
            if (self.verify.status, self.verify.reason) != ("not_run", "dry_run"):
                raise ValueError(
                    "a dry run has nothing to verify and records `not_run` with the reason "
                    "`dry_run`"
                )
            return
        if self.idempotent is None:
            raise ValueError("an apply says whether it changed anything")
        if self.idempotent != (not self.file_edits):
            raise ValueError(
                f"idempotent is {self.idempotent} over {len(self.file_edits)} written file(s); "
                f"it records what happened to the bytes and nothing else"
            )

    def _check_the_clock(self) -> None:
        """A phase that did not run has no duration, which is `timings`' rule.

        A baseline under `not_run` ran before a refused write, so its verification ran.
        """
        verified = self.verify is not None and (
            self.verify.status != "not_run" or self.verify.baseline is not None
        )
        for name, expected in (
            ("plan_ms", self.mode in FIX_MODES),
            ("apply_ms", self.mode == "apply"),
            ("verify_ms", verified),
            ("model_ms", self.model is not None),
        ):
            if (getattr(self.timings, name) is not None) != expected:
                raise ValueError(
                    f"{name} is the duration of a phase that ran, and a {self.mode!r} run "
                    f"{'ran' if expected else 'did not run'} that one"
                )


class UndoFile(_Frozen):
    """One file `obelize undo` was asked to put back, and what became of it."""

    path: RelativePath
    outcome: UndoOutcome
    reason: UndoSkip | None = None
    recorded_sha256: Sha256
    current_sha256: Sha256 | None = None
    # The pre-migration copy in the run folder, recorded even on a skip so the refusal says where
    # the original bytes are.
    snapshot: RelativePath

    @model_validator(mode="after")
    def _check(self) -> UndoFile:
        if (self.reason is None) != (self.outcome == "reverted"):
            raise ValueError(
                f"{self.path} is {self.outcome!r} with reason {self.reason!r}; a skip says "
                f"why and a revert has nothing to say"
            )
        if self.reason == "hash_mismatch":
            if self.current_sha256 in (None, self.recorded_sha256):
                raise ValueError(
                    f"{self.path} is `hash_mismatch` and the hash on the disk is "
                    f"{'not recorded' if self.current_sha256 is None else 'the recorded one'}; "
                    f"that code is exactly the case where the two differ"
                )
            return self
        if self.current_sha256 not in (None, self.recorded_sha256):
            raise ValueError(
                f"{self.path} is {self.outcome!r} over bytes that are neither the ones the "
                f"run wrote nor unreadable; the only word for that is `hash_mismatch`"
            )
        if self.outcome == "reverted" and self.current_sha256 is None:
            raise ValueError(f"{self.path} was put back and what it held first is not recorded")
        return self

    @property
    def restored(self) -> bool:
        """Whether the file holds what it held before the run: put back now, or already.

        A snapshot is named by its sha256, so a `hash_mismatch` whose current hash is that name is
        the original again, after an earlier undo.
        """
        return self.outcome == "reverted" or (
            self.reason == "hash_mismatch"
            and PurePosixPath(self.snapshot).name == self.current_sha256
        )


class UndoRecord(_Frozen):
    """The `undo.json` document one `obelize undo` writes into the run folder it reverted."""

    # `run_id` is the reverted run's. No summary count: `files[]` has a row for every file the run
    # wrote, skipped ones included, and a count could disagree with it.
    run_id: RunId
    obelize_version: str
    exit_code: ExitCode
    argv: tuple[str, ...] = ()
    undone_at: Instant
    files: tuple[UndoFile, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> UndoRecord:
        paths = [row.path for row in self.files]
        if paths != sorted(paths):
            raise ValueError("the files are written in path order, `file_edits[]`'s own order")
        if len(set(paths)) != len(paths):
            raise ValueError("one file is undone once; two rows for one path is two answers")
        restored = [row for row in self.files if row.restored]
        if (self.exit_code == 0) != bool(restored and len(restored) == len(self.files)):
            raise ValueError(
                f"exit {self.exit_code} over {len(restored)} of {len(self.files)} file(s) holding "
                f"the original; `0` is every file reverted, or already the original, and `4` is "
                f"anything else"
            )
        return self


__all__ = [
    "RUN_ID_PATTERN",
    "ConsultationSkip",
    "FileEdit",
    "Instant",
    "ModelDocument",
    "PlanDocument",
    "ProposalRecord",
    "RunConfig",
    "RunCounts",
    "RunFixer",
    "RunFixerFile",
    "RunId",
    "RunJournal",
    "RunLimitation",
    "RunModel",
    "RunPack",
    "RunPlatform",
    "RunPlugin",
    "RunPython",
    "RunRecord",
    "RunRefusal",
    "RunTimings",
    "UndoFile",
    "UndoRecord",
    "Withheld",
]
