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
Outcome = Literal["edited", "nothing", "refused", "covered", "unchanged", "failed", "skipped"]
SETTLED: Final = ("edited", "covered", "unchanged")


@dataclass(frozen=True, slots=True)
class Row:
    """A flagged place, with what the pack says about it."""

    path: str
    line: int
    symbol: str | None
    note: str
    # The import of a name, which has nothing to move by itself: its uses carry the change.
    is_import: bool = False


@dataclass(slots=True)
class _Waiting:
    """A place not yet asked about, and the line it is on in the copy now."""

    row: Row
    now: int


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
        return sum(1 for one in self.decisions if one.outcome not in SETTLED)

    @property
    def settled(self) -> tuple[str, ...]:
        """The files with a place moved, covered or judged to need nothing."""
        return tuple(sorted({one.row.path for one in self.decisions if one.outcome in SETTLED}))

    @property
    def unchanged(self) -> tuple[str, ...]:
        """`path:line` of each place the model judged to need no edit."""
        return tuple(
            f"{one.row.path}:{one.row.line}" for one in self.decisions if one.outcome == "unchanged"
        )


def rows(
    findings: Sequence[Finding], pack: PackDocument, hints: Mapping[str, str] | None = None
) -> list[Row]:
    """The withheld rows a flagged change of `pack` claims, each with that change's words and, if
    `hints` hold one for the name or the longest name above it, that."""
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
                row = Row(
                    finding.path,
                    finding.line,
                    finding.symbol,
                    note + _hint(finding, hints),
                    finding.kind == "import",
                )
                found.setdefault(key, row)
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
    """Ask about each place and write the answers the guard accepts into `work`.

    A place the model says needs no edit is settled on the tests' word. The place with the most
    lines below it goes first, so an answer moves the places still waiting as little as it can, and
    each is found again where the edits above or below it left it. The import of a name is asked
    last: once every place that uses it was settled, it is covered.
    """
    decisions: list[Decision] = []
    tokens_in = tokens_out = asked = 0
    imports = pack.to_modules() or pack.match.imports
    # What each name of the file in hand had moved, and what it had left.
    moved: set[str | None] = set()
    left: set[str | None] = set()

    def decide(
        one: _Waiting, outcome: Outcome, detail: str, proposal: EditProposal | None = None
    ) -> None:
        decisions.append(Decision(one.row, outcome, detail, proposal))
        if not one.row.is_import:
            (moved if outcome in SETTLED else left).add(one.row.symbol)

    for path in sorted({row.path for row in flagged}):
        waiting = [_Waiting(row, row.line) for row in flagged if row.path == path]
        moved.clear()
        left.clear()
        while waiting:
            uses = [w for w in waiting if not w.row.is_import]
            one = max(uses or waiting, key=_now)
            waiting.remove(one)
            row = one.row
            if row.is_import and row.symbol in moved and row.symbol not in left:
                decide(one, "covered", "the places that use it were moved")
                continue
            if asked >= limit:
                decide(one, "skipped", f"{limit} questions were asked already")
                continue
            data = (work / path).read_bytes()
            context = base.excerpt(path, data, one.now, environ)
            if context is None:
                decide(one, "skipped", "the file does not parse")
                continue
            asked += 1
            consultation = base.Consultation(
                context=context,
                line=one.now,
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
                decide(one, "failed", f"{error.failure}: {error.detail}")
                continue
            tokens_in += reply.tokens_in
            tokens_out += reply.tokens_out
            if reply.proposal is None:
                if reply.unchanged:
                    decide(one, "unchanged", reply.unchanged)
                else:
                    decide(one, "nothing", "the model proposed no edit")
                continue
            checked = guard.check(reply.proposal, consultation=consultation, root=work, before=data)
            if checked.after is None:
                decide(one, "refused", f"{checked.refusal}: {checked.detail}", reply.proposal)
                continue
            (work / path).write_bytes(checked.after)
            decide(one, "edited", checked.detail, reply.proposal)
            first, last = reply.proposal.start_line, reply.proposal.end_line
            longer = len(base.LINE_BREAK.split(reply.proposal.replacement)) - (last - first + 1)
            for other in list(waiting):
                if first <= other.now <= last:
                    waiting.remove(other)
                    decide(other, "covered", "an accepted answer replaced this line")
                else:
                    other.now += sum(count for at, count in checked.shifts if at <= other.now) + (
                        longer if other.now > last else 0
                    )
    return Resolved(tuple(decisions), tokens_in, tokens_out)


def _hint(finding: Finding, hints: Mapping[str, str] | None) -> str:
    names = [
        name
        for name in hints or ()
        if finding.symbol and (finding.symbol == name or finding.symbol.startswith(f"{name}."))
    ]
    return f" {hints[max(names, key=len)]}" if names and hints else ""


def _now(waiting: _Waiting) -> int:
    return waiting.now


__all__ = ["ASK_LIMIT", "Decision", "Outcome", "Resolved", "Row", "resolve", "rows"]
