"""One run's consultation: the questions, the guarded answers, and what became of each.

A model edit and a rule edit never share a file (`folded` asserts it). A file takes one model edit
per run, the first accepted in document order, since each `after` is a whole file. A proposal is
placed before the write, so a dry run shows it, and graded after it against the disk.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from obelize import __version__, fsutil
from obelize.models import (
    ConsultationSkip,
    Edit,
    ModelDocument,
    ProposalRecord,
    RunModel,
)
from obelize.providers import base, guard
from obelize.providers import openai_compat as adapter
from obelize.transforms import codemod

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from obelize.fsutil import Apply, Change
    from obelize.models import (
        Finding,
        ImpactPlan,
        ModelConfig,
        ProposalOutcome,
        ProviderFailure,
    )
    from obelize.packs.schema import PackDocument

# The run folder's model directory, and the index a reader wanting only the model opens.
MODEL = "model"
MODEL_INDEX = "model.json"

# Numbered per consultation, not per proposal: an unreachable endpoint produces none.
PROPOSAL = "proposals-{index}.json"


@dataclass(frozen=True, slots=True)
class Asked:
    """One question, and the exact bytes that carried it."""

    index: int
    consultation: base.Consultation
    # From the provider's own `request`, so the hash is of what went on the wire.
    prompt: bytes

    @property
    def path(self) -> str:
        return self.consultation.context.path

    @property
    def sha256(self) -> str:
        return fsutil.sha256(self.prompt)


@dataclass(frozen=True, slots=True)
class Decided:
    """One question's outcome: a `failure`, a `reply` with no proposal, or `reply` and `checked`."""

    asked: Asked
    reply: base.Reply | None = None
    failure: ProviderFailure | None = None
    detail: str | None = None
    checked: guard.Checked | None = None

    @property
    def accepted(self) -> bool:
        """Whether the guard accepted it, which is not a write."""
        return self.checked is not None and self.checked.accepted


@dataclass(frozen=True, slots=True)
class Placed:
    """One accepted proposal that holds its file, and the bytes it makes of it."""

    index: int
    path: str
    after: bytes


@dataclass(frozen=True, slots=True)
class Session:
    """Everything one run's consultation decided, before any of it was written."""

    settings: ModelConfig
    decided: tuple[Decided, ...] = ()
    skipped: tuple[base.Skipped, ...] = ()
    placed: tuple[Placed, ...] = ()

    @property
    def proposals(self) -> int:
        """How many proposals came back, not how many questions were asked."""
        return sum(1 for one in self.decided if one.reply is not None and one.reply.proposal)

    @property
    def tokens_in(self) -> int:
        return sum(one.reply.tokens_in for one in self.decided if one.reply is not None)

    @property
    def tokens_out(self) -> int:
        return sum(one.reply.tokens_out for one in self.decided if one.reply is not None)

    @property
    def numbers(self) -> dict[str, tuple[int, ...]]:
        """Path -> the proposal numbers that produced it, for `FileEdit`."""
        return {one.path: (one.index,) for one in self.placed}


def consult(
    provider: base.ModelProvider,
    settings: ModelConfig,
    *,
    root: Path,
    findings: Sequence[Finding],
    plans: Sequence[ImpactPlan],
    sources: Mapping[str, bytes],
    pack: PackDocument,
    environ: Mapping[str, str],
) -> Session:
    """Ask every question this repository raises, and guard every answer.

    Asking stays in `base.consult`, the one loop; this adds each question's bytes and the guard's
    verdict. One request per question, no retries: a retry would record one hash for two prompts.
    """
    result = base.consult(
        provider, findings=findings, plans=plans, sources=sources, pack=pack, environ=environ
    )
    decided: list[Decided] = []
    for index, answer in enumerate(result.answers, start=1):
        consultation = answer.consultation
        one = Asked(index, consultation, provider.request(consultation))
        if answer.reply is None:
            decided.append(Decided(one, failure=answer.failure, detail=answer.error))
            continue
        if answer.reply.proposal is None:
            decided.append(Decided(one, reply=answer.reply))
            continue
        checked = guard.check(
            answer.reply.proposal,
            consultation=consultation,
            root=root,
            before=sources[one.path],
        )
        decided.append(Decided(one, reply=answer.reply, checked=checked))
    return Session(settings, tuple(decided), result.skipped, placement(decided))


def placement(decided: Iterable[Decided]) -> tuple[Placed, ...]:
    """The accepted proposals that become edits: the first in each file."""
    held: dict[str, Placed] = {}
    for one in decided:
        if not one.accepted or one.asked.path in held:
            continue
        assert one.checked is not None  # noqa: S101 - `accepted` is exactly this
        assert one.checked.after is not None  # noqa: S101 - and `Checked` pairs the two
        held[one.asked.path] = Placed(one.asked.index, one.asked.path, one.checked.after)
    return tuple(held.values())


def folded(run: codemod.Run, session: Session) -> codemod.Run:
    """The driver's run with the placed proposals in it, ready to be planned.

    Each placed row becomes `model_proposed` and keeps its bail. Findings are deliberately left
    alone: they grade the code as scanned.
    """
    if not session.placed:
        return run
    by_path = {one.path: one for one in session.placed}
    files = []
    for outcome in run.files:
        placed = by_path.pop(outcome.path, None)
        if placed is None:
            files.append(outcome)
            continue
        if outcome.written:
            raise codemod.CodemodError(
                f"{outcome.path} was rewritten by the pack rules and a model proposed an "
                f"edit for it; a consulted file has a withheld finding, so the rules leave it "
                f"exactly as it was, and this is two answers for one path"
            )
        files.append(
            codemod.Outcome(
                path=outcome.path,
                before=outcome.before,
                after=placed.after,
                edits=_rows(outcome.edits, session, placed),
            )
        )
    if by_path:
        raise codemod.CodemodError(
            f"a proposal was placed for {sorted(by_path)}, which this run did not read"
        )
    return replace(run, files=tuple(files))


def _rows(edits: Sequence[Edit], session: Session, placed: Placed) -> tuple[Edit, ...]:
    """One file's rows, with the question's line re-graded `model_proposed`.

    `rule_id` is dropped: `Edit` refuses a model proposal that names a pack rule.
    """
    line = next(
        one.asked.consultation.line for one in session.decided if one.asked.index == placed.index
    )
    rows = []
    for row in edits:
        if row.line != line or row.status != "needs_review":
            rows.append(row)
            continue
        rows.append(
            Edit(
                path=row.path,
                line=row.line,
                status="model_proposed",
                reason=row.reason,
                caused_by=row.caused_by,
                warnings=row.warnings,
            )
        )
    return tuple(rows)


def writable(
    changes: Sequence[Change], session: Session, *, apply: bool, accept: bool
) -> tuple[Change, ...]:
    """The changes an apply may write: model edits only with both `apply` and `accept`.

    `plan.json` and `patch.diff` hold them regardless, since a dry run is how a person decides on
    `--accept-model`.
    """
    if apply and accept:
        return tuple(changes)
    held = {one.path for one in session.placed}
    return tuple(change for change in changes if change.path not in held)


def records(
    session: Session,
    *,
    applied: Apply | None = None,
    apply: bool = False,
    accept: bool = False,
) -> tuple[ProposalRecord, ...]:
    """One `model/proposals-<n>.json` per consultation, in the order asked."""
    placed = {one.index for one in session.placed}
    written = {row.path for row in applied.written} if applied is not None else set()
    return tuple(
        _record(
            one,
            session.settings,
            _outcome(one, placed, written, apply=apply, accept=accept),
        )
        for one in session.decided
    )


def _outcome(
    one: Decided,
    placed: set[int],
    written: set[str],
    *,
    apply: bool,
    accept: bool,
) -> ProposalOutcome:
    """The first `ProposalOutcome` that holds; the order is the decision."""
    if one.failure is not None:
        return "unanswered"
    if one.reply is None or one.reply.proposal is None:
        return "nothing_proposed"
    if not one.accepted:
        return "guard_refused"
    if not apply:
        return "not_applied"
    if not accept:
        return "not_accepted"
    if one.asked.index not in placed:
        return "file_already_proposed"
    if one.asked.path not in written:
        return "write_refused"
    return "written"


def _record(one: Decided, settings: ModelConfig, outcome: ProposalOutcome) -> ProposalRecord:
    """One consultation as the run folder holds it."""
    consultation = one.asked.consultation
    assert settings.model is not None  # noqa: S101 - a configured provider names one
    return ProposalRecord(
        index=one.asked.index,
        path=consultation.context.path,
        line=consultation.line,
        symbol=consultation.symbol,
        bail=consultation.bail,
        context_start_line=consultation.context.start_line,
        context_end_line=consultation.context.end_line,
        prompt_sha256=one.asked.sha256,
        prompt=one.asked.prompt.decode("utf-8") if settings.log_prompts else None,
        provider=settings.provider,
        model=settings.model,
        tokens_in=one.reply.tokens_in if one.reply is not None else 0,
        tokens_out=one.reply.tokens_out if one.reply is not None else 0,
        outcome=outcome,
        failure=one.failure,
        refusal=None if one.checked is None else one.checked.refusal,
        detail=one.detail if one.checked is None else one.checked.detail,
        proposal=None if one.reply is None else one.reply.proposal,
    )


def summary(session: Session, written: Sequence[ProposalRecord]) -> RunModel:
    """`run.json`'s `model`: the seven numbers `docs/RUN_FOLDER.md` names."""
    settings = session.settings
    assert settings.host is not None  # noqa: S101 - a configured provider has a base_url
    assert settings.model is not None  # noqa: S101 - and a model name
    return RunModel(
        provider=settings.provider,
        host=settings.host,
        model=settings.model,
        proposals=session.proposals,
        accepted=sum(1 for row in written if row.outcome == "written"),
        tokens_in=session.tokens_in,
        tokens_out=session.tokens_out,
    )


def document(session: Session, model: RunModel) -> ModelDocument:
    """`model/model.json`: the summary, and the rows nobody was asked about."""
    return ModelDocument(
        obelize_version=__version__,
        summary=model,
        consulted=len(session.decided),
        skipped=tuple(
            ConsultationSkip(path=row.path, line=row.line, reason=row.reason)
            for row in session.skipped
        ),
    )


def artefacts(
    index: ModelDocument, written: Sequence[ProposalRecord]
) -> tuple[tuple[str, bytes], ...]:
    """Everything a run with a model adds to the folder, as name -> bytes."""
    files = [(f"{MODEL}/{MODEL_INDEX}", _json(index))]
    files.extend((f"{MODEL}/{PROPOSAL.format(index=row.index)}", _json(row)) for row in written)
    return tuple(files)


def _json(model: ModelDocument | ProposalRecord) -> bytes:
    return model.model_dump_json(indent=2).encode("utf-8") + b"\n"


def heading(settings: ModelConfig) -> str:
    """The line printed before a run and first by `--show-context`.

    The host, not the URL: a query string can carry a credential.
    """
    if settings.provider == "none":
        return "No model provider is configured, so nothing is sent (model.provider: none)."
    return f"Model: {settings.model} at {settings.host} ({settings.provider})."


def shown(
    settings: ModelConfig,
    asked: Sequence[base.Consultation],
    skipped: Sequence[base.Skipped],
) -> list[str]:
    """`--show-context`: every string the payload carries, once each and readable.

    Deliberately not the JSON: one long line of escaped newlines hides a credential from an audit.
    """
    lines = [
        heading(settings),
        "",
        f"Nothing below has been sent. {len(asked)} question(s); {len(skipped)} finding(s) "
        f"left for review are not asked about.",
        "",
        "--- system prompt ---",
        adapter.SYSTEM_PROMPT,
    ]
    if settings.provider != "none":
        lines += [
            "",
            "--- request fields ---",
            f"model={settings.model} temperature=0 stream=false response_format=json_object",
        ]
    for index, one in enumerate(asked, start=1):
        lines += [
            "",
            f"--- {index}/{len(asked)} {one.context.path}:{one.line} {one.bail}, "
            f"context lines {one.context.start_line}..{one.context.end_line} ---",
            adapter.question(one),
        ]
    return lines


__all__ = [
    "MODEL",
    "MODEL_INDEX",
    "PROPOSAL",
    "Asked",
    "Decided",
    "Placed",
    "Session",
    "artefacts",
    "consult",
    "document",
    "folded",
    "heading",
    "placement",
    "records",
    "shown",
    "summary",
    "writable",
]
