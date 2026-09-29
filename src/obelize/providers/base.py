"""Which withheld rows a model is asked about, with what context; `consult` is the only asking loop.

Only rows the rules could not decide are asked, never a pack's refusal; each row not asked is
recorded with its reason. A context is the smallest `def`/`class` holding the whole binding group,
else a window, and is never truncated: the guard's range check would mean nothing on a cut range.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from obelize.models import WITHHELD
from obelize.verify import redact

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Mapping, Sequence

    from obelize.models import (
        BailCode,
        ConsultSkip,
        EditProposal,
        Finding,
        ImpactPlan,
        ProviderFailure,
    )
    from obelize.packs.schema import PackDocument

# Max lines in any context. tests/fixtures/providers/deep/long.py's eighty-eight-line function
# must stay over it or that fixture measures nothing.
CONTEXT_LINE_LIMIT = 80

# Lines either side of the binding group in the fallback window; docs/THREAT_MODEL.md TM-3 cites it.
CONTEXT_MARGIN = 20

# Bails never asked about; any other `needs_review` bail is (exceptions, not an allowlist).
# file_not_fully_migrated: its `caused_by` rows are asked instead. flag_only_surface: the pack's
# deliberate refusal. configure_consumed_elsewhere: the defect is in the module still using it.
NOT_CONSULTED: dict[BailCode, ConsultSkip] = {
    "file_not_fully_migrated": "atomicity_only",
    "flag_only_surface": "pack_refused",
    "configure_consumed_elsewhere": "consumed_elsewhere",
}

# libcst's line terminators; `str.splitlines` also splits on form feed and Unicode separators.
# `guard` splices by these same numbers, so a proposal is checked and written against one file.
LINE_BREAK = re.compile(r"\r\n|\r|\n")


class ProviderError(Exception):
    """An adapter's failure as a `ProviderFailure` word; it ends one consultation, not the run.

    `detail` is shown to the user, so an adapter puts nothing in it that `redact` has not seen.
    """

    def __init__(self, failure: ProviderFailure, detail: str) -> None:
        super().__init__(f"{failure}: {detail}")
        self.failure = failure
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Context:
    """The exact text that leaves the machine, and the range it came from."""

    path: str
    # 1-based, inclusive at both ends, like `Finding.line`.
    start_line: int
    end_line: int
    # Already redacted by `obelize.verify.redact`, the only redactor.
    text: str

    def holds(self, start: int, end: int) -> bool:
        """Whether a proposed range is inside the sent one: the guard's only reading of "inside"."""
        return self.start_line <= start and end <= self.end_line


@dataclass(frozen=True, slots=True)
class Consultation:
    """One question: one withheld row, with the least that can answer it."""

    context: Context
    line: int
    column: int
    symbol: str | None
    # Sent as the code itself; there is no prose per bail (docs/SCAN_VOCABULARY.md defines each).
    bail: BailCode
    pack_id: str
    # The pack's `to.package`: the only distribution a proposal may add an import from.
    to_package: str
    # Its import names (every `rename_import` `to_module`); the prompt and the guard both read it.
    to_modules: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Reply:
    """One answer and its reported token cost; `proposal=None` is a normal answer, not an error."""

    proposal: EditProposal | None
    tokens_in: int = 0
    tokens_out: int = 0


class ModelProvider(Protocol):
    """One question in, one answer out, no state; a Protocol so a test double inherits nothing."""

    def request(self, consultation: Consultation) -> bytes:
        """The exact bytes `propose` would send, which the run folder hashes and may log."""
        ...  # pragma: no cover - a protocol body is never executed

    def propose(self, consultation: Consultation) -> Reply:
        """Answer one consultation, or raise `ProviderError`."""
        ...  # pragma: no cover - a protocol body is never executed


@dataclass(frozen=True, slots=True)
class Answered:
    """One consultation and what came back, including nothing."""

    consultation: Consultation
    reply: Reply | None
    # The provider's sentence when it raised; `reply` is None iff this and `failure` are set.
    error: str | None = None
    # The word the evidence records.
    failure: ProviderFailure | None = None


@dataclass(frozen=True, slots=True)
class Skipped:
    path: str
    line: int
    reason: ConsultSkip


@dataclass(frozen=True, slots=True)
class Consulted:
    """Everything one pass decided, in document order."""

    answers: tuple[Answered, ...] = ()
    skipped: tuple[Skipped, ...] = ()

    @property
    def proposals(self) -> tuple[EditProposal, ...]:
        """Every proposal that came back, before any guard has seen one."""
        return tuple(
            answer.reply.proposal
            for answer in self.answers
            if answer.reply is not None and answer.reply.proposal is not None
        )

    @property
    def tokens_in(self) -> int:
        return sum(answer.reply.tokens_in for answer in self.answers if answer.reply)

    @property
    def tokens_out(self) -> int:
        return sum(answer.reply.tokens_out for answer in self.answers if answer.reply)


def consult(
    provider: ModelProvider,
    *,
    findings: Sequence[Finding],
    plans: Sequence[ImpactPlan],
    sources: Mapping[str, bytes],
    pack: PackDocument,
    environ: Mapping[str, str],
) -> Consulted:
    """Ask `provider` about every withheld row that qualifies, and record the rest.

    `sources`: bytes of the files this run could write (`codemod.Run.files`) by relative path.
    """
    asked, skipped = questions(
        findings=findings, plans=plans, sources=sources, pack=pack, environ=environ
    )
    answers = []
    for consultation in asked:
        try:
            reply: Reply | None = provider.propose(consultation)
        except ProviderError as error:
            answers.append(Answered(consultation, None, error.detail, error.failure))
        else:
            answers.append(Answered(consultation, reply))
    return Consulted(tuple(answers), tuple(skipped))


def questions(
    *,
    findings: Sequence[Finding],
    plans: Sequence[ImpactPlan],
    sources: Mapping[str, bytes],
    pack: PackDocument,
    environ: Mapping[str, str],
) -> tuple[list[Consultation], list[Skipped]]:
    """The selection alone, with no provider, so an answer key can grade it by itself."""
    groups = _groups(plans)
    scopes: dict[str, list[tuple[int, int]]] = {}
    asked: list[Consultation] = []
    skipped: list[Skipped] = []
    for finding in findings:
        if finding.scan_status not in WITHHELD:
            continue
        reason = _refuse(finding, sources)
        if reason is None:
            data = sources[finding.path]
            if finding.path not in scopes:
                scopes[finding.path] = _scopes(data)
            lines = split_lines(data)
            span = _range(
                finding.line,
                groups.get((finding.path, finding.line), frozenset()),
                scopes[finding.path],
                len(lines),
            )
            if span is None:
                reason = "context_too_large"
            else:
                asked.append(_question(finding, span, lines, pack, environ))
        if reason is not None:
            skipped.append(Skipped(finding.path, finding.line, reason))
    return asked, skipped


def _refuse(finding: Finding, sources: Mapping[str, bytes]) -> ConsultSkip | None:
    """The skip reason or None; order matters (a withheld manifest is `not_a_source_file`)."""
    if finding.scan_status != "needs_review":
        return "not_needs_review"
    if finding.path not in sources:
        return "not_a_source_file"
    assert finding.bail is not None  # noqa: S101 - a withheld status always names a bail
    return NOT_CONSULTED.get(finding.bail)


def _groups(plans: Sequence[ImpactPlan]) -> dict[tuple[str, int], frozenset[int]]:
    """Each group line's whole group; a union, as one line can end one group and start the next."""
    collected: dict[tuple[str, int], set[int]] = {}
    for plan in plans:
        for binding in plan.bindings:
            lines = {binding.ctor_line, *binding.use_lines}
            for line in lines:
                collected.setdefault((plan.path, line), set()).update(lines)
    return {key: frozenset(value) for key, value in collected.items()}


def _scopes(data: bytes) -> list[tuple[int, int]]:
    """Every `def` and `class` as inclusive 1-based line ranges."""
    wrapper = MetadataWrapper(cst.parse_module(data), unsafe_skip_copy=True)
    collector = _Scopes()
    wrapper.visit(collector)
    return collector.found


class _Scopes(cst.CSTVisitor):
    """`_scopes`' visitor; a definition's range includes its decorators."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[int, int]] = []

    def _record(self, node: cst.CSTNode) -> None:
        position = self.get_metadata(PositionProvider, node)
        self.found.append((position.start.line, position.end.line))

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self._record(node)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self._record(node)


def _range(
    line: int,
    group: Iterable[int],
    scopes: Sequence[tuple[int, int]],
    total: int,
) -> tuple[int, int] | None:
    """The smallest scope holding the group within the limit, else the margin window, else None."""
    lines = {line, *group}
    first, last = min(lines), max(lines)
    holding = [(start, end) for start, end in scopes if start <= first and last <= end]
    if holding:
        start, end = min(holding, key=lambda span: span[1] - span[0])
        if end - start + 1 <= CONTEXT_LINE_LIMIT:
            return start, end
    start = max(1, first - CONTEXT_MARGIN)
    end = min(total, last + CONTEXT_MARGIN)
    if end - start + 1 > CONTEXT_LINE_LIMIT:
        return None
    return start, end


def split_lines(data: bytes) -> list[str]:
    """One file as its lines, terminators kept, numbered the way libcst does."""
    text = data.decode(cst.parse_module(data).encoding)
    parts = LINE_BREAK.split(text)
    breaks = LINE_BREAK.findall(text)
    joined = [part + break_ for part, break_ in zip(parts[:-1], breaks, strict=True)]
    if parts[-1]:
        joined.append(parts[-1])
    return joined


def _to_modules(pack: PackDocument) -> tuple[str, ...]:
    """Every `to_module` of the pack's `rename_import` rules; empty authorises no new import."""
    return tuple(
        sorted(
            {change.params.to_module for change in pack.changes if change.kind == "rename_import"}
        )
    )


def _question(
    finding: Finding,
    span: tuple[int, int],
    lines: Sequence[str],
    pack: PackDocument,
    environ: Mapping[str, str],
) -> Consultation:
    """One `Consultation`, with the context redacted on the way in."""
    start, end = span
    assert finding.bail is not None  # noqa: S101 - `_refuse` returned, so it is set
    return Consultation(
        context=Context(
            path=finding.path,
            start_line=start,
            end_line=end,
            text=redact.redact("".join(lines[start - 1 : end]), environ),
        ),
        line=finding.line,
        column=finding.column,
        symbol=finding.symbol,
        bail=finding.bail,
        pack_id=pack.id,
        to_package=pack.to.package,
        to_modules=_to_modules(pack),
        limitations=tuple(pack.limitations),
    )


__all__ = [
    "CONTEXT_LINE_LIMIT",
    "CONTEXT_MARGIN",
    "LINE_BREAK",
    "NOT_CONSULTED",
    "Answered",
    "Consultation",
    "Consulted",
    "Context",
    "ModelProvider",
    "ProviderError",
    "Reply",
    "Skipped",
    "consult",
    "questions",
    "split_lines",
]
