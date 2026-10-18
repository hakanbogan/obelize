"""The places a pack could only flag, put to a model one at a time, in a copy.

A flagged row is a place the pack names and will not rewrite: a name the library removed, a
signature it changed. Each is put to a model with the pack's own words about it and the lines around
it, and the answer goes through the guard that checks every proposal (`providers.guard`): it must
stay inside what was sent, parse, and add no import or name beyond the question. An accepted answer
is written to the copy, bottom of a file first so the lines above keep their numbers, and nothing
here touches the repository: the tests decide whether the copy is kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from obelize.models import WITHHELD
from obelize.packs.schema import FlagOnlyChange
from obelize.providers import base, guard
from obelize.transforms.kinds.flag_only import FlagOnly

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from obelize.models import EditProposal, Finding
    from obelize.packs.schema import PackDocument

# The most places one trial asks about: each is a request to a model, which costs money and time.
ASK_LIMIT: Final = 50
Outcome = Literal["edited", "nothing", "refused", "covered", "failed", "skipped"]


@dataclass(frozen=True, slots=True)
class Row:
    """A flagged place, with what the pack says about it."""

    path: str
    line: int
    symbol: str | None
    note: str


@dataclass(frozen=True, slots=True)
class Decision:
    row: Row
    outcome: Outcome
    detail: str = ""
    proposal: EditProposal | None = None


@dataclass(frozen=True, slots=True)
class Resolved:
    decisions: tuple[Decision, ...]
    tokens_in: int
    tokens_out: int

    @property
    def edited(self) -> tuple[str, ...]:
        return tuple(sorted({one.row.path for one in self.decisions if one.outcome == "edited"}))

    @property
    def left(self) -> int:
        return sum(1 for one in self.decisions if one.outcome not in ("edited", "covered"))


def rows(findings: Sequence[Finding], pack: PackDocument) -> list[Row]:
    """The withheld rows a flagged change of `pack` claims, each with that change's words."""
    found: dict[tuple[str, int, str | None], Row] = {}
    for change in pack.changes:
        if not isinstance(change, FlagOnlyChange):
            continue
        claims = FlagOnly(change)
        note = f"{change.params.message} {change.params.suggestion}"
        for finding in findings:
            if (
                finding.scan_status in WITHHELD
                and finding.kind != "manifest"
                and claims.claims(finding)
            ):
                key = (finding.path, finding.line, finding.symbol)
                found.setdefault(key, Row(finding.path, finding.line, finding.symbol, note))
    return sorted(found.values(), key=lambda row: (row.path, row.line))


def resolve(
    work: Path,
    flagged: Sequence[Row],
    *,
    provider: base.ModelProvider,
    pack: PackDocument,
    environ: Mapping[str, str],
    limit: int = ASK_LIMIT,
) -> Resolved:
    """Ask about each place and write the answers the guard accepts into `work`."""
    decisions: list[Decision] = []
    tokens_in = tokens_out = asked = 0
    imports = pack.to_modules() or pack.match.imports
    for path in sorted({row.path for row in flagged}):
        covered_from: int | None = None
        for row in sorted((one for one in flagged if one.path == path), key=_line, reverse=True):
            if covered_from is not None and row.line >= covered_from:
                decisions.append(Decision(row, "covered", "an accepted answer replaced this line"))
                continue
            if asked >= limit:
                decisions.append(Decision(row, "skipped", f"{limit} questions were asked already"))
                continue
            data = (work / path).read_bytes()
            context = base.excerpt(path, data, row.line, environ)
            if context is None:
                decisions.append(Decision(row, "skipped", "the file does not parse"))
                continue
            asked += 1
            consultation = base.Consultation(
                context=context,
                line=row.line,
                column=0,
                symbol=row.symbol,
                bail="flag_only_surface",
                pack_id=pack.id,
                to_package=pack.to.package,
                to_modules=imports,
                limitations=(),
                note=row.note,
            )
            try:
                reply = provider.propose(consultation)
            except base.ProviderError as error:
                decisions.append(Decision(row, "failed", f"{error.failure}: {error.detail}"))
                continue
            tokens_in += reply.tokens_in
            tokens_out += reply.tokens_out
            if reply.proposal is None:
                decisions.append(Decision(row, "nothing", "the model proposed no edit"))
                continue
            checked = guard.check(reply.proposal, consultation=consultation, root=work, before=data)
            if checked.after is None:
                decisions.append(
                    Decision(row, "refused", f"{checked.refusal}: {checked.detail}", reply.proposal)
                )
                continue
            (work / path).write_bytes(checked.after)
            covered_from = reply.proposal.start_line
            decisions.append(Decision(row, "edited", checked.detail, reply.proposal))
    return Resolved(tuple(decisions), tokens_in, tokens_out)


def _line(row: Row) -> int:
    return row.line


__all__ = ["ASK_LIMIT", "Decision", "Outcome", "Resolved", "Row", "resolve", "rows"]
