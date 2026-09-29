"""Decide what each binding group withholds (rung 5), from the records `scan/analysis.py` made.

A group is atomic: its constructor and every use are withheld together, since a half-rewritten
group breaks working code. What escapes is analysis's call; this reads only `escape_lines`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from obelize.models import BailCode, Binding

if TYPE_CHECKING:  # pragma: no cover - typing only
    from obelize.models import Finding
    from obelize.scan.analysis import Analysis, Receiver

# Closed here, where raised; `impact/planner.py` merges them into the ladder.
BAILS: frozenset[BailCode] = frozenset(
    {
        "class_attr_binding",
        "model_object_escapes",
        "multiple_assignments",
    }
)

# Beside the codes, so the raising modules cannot drift into separate ladders.
RUNG: Final[dict[BailCode, int]] = {
    "class_attr_binding": 5,
    "model_object_escapes": 5,
    "multiple_assignments": 5,
}

# The code a group names when several fire; no fixture pins it. Each makes the next moot: a
# class-body site is never rewritten, an unknown referent makes escapes unknowable, and
# `model_object_escapes` presupposes the group resolved.
ORDER: Final[tuple[BailCode, ...]] = (
    "class_attr_binding",
    "multiple_assignments",
    "model_object_escapes",
)


@dataclass(frozen=True, slots=True)
class Group:
    """One binding group: what holds it, what withholds it, what it governs."""

    receiver: Receiver
    # `None` when the group is closed-world.
    bail: BailCode | None
    # The constructor line and every use line.
    lines: tuple[int, ...]

    def holds(self, finding: Finding) -> bool:
        """Whether `finding` is this group's constructor or one of its uses, by symbol and line.

        A `GenerationConfig(...)` passed to the group's `GenerativeModel(...)` shares its line.
        """
        if finding.line not in self.lines:
            return False
        symbol = finding.symbol or ""
        held = self.receiver.receiver
        return symbol == held or symbol.rpartition(".")[0] == held

    def row(self, path: str, bail: BailCode | None) -> Binding:
        """The group as a report row, withheld by `bail` or by nothing."""
        return Binding(
            kind=self.receiver.kind,
            name=self.receiver.name,
            scope=self.receiver.scope,
            path=path,
            ctor_line=self.receiver.ctor_line,
            use_lines=self.receiver.use_lines,
            scan_status="needs_review" if bail is not None else "eligible",
            bail=bail,
        )


def refusal(receiver: Receiver) -> BailCode | None:
    """The group's own defect, or `None`; `ORDER` picks one when several fire.

    `class_attr_binding` is the constructor's site (a class body), not the `self.x` spelling: a
    `self_attr` built in `__init__` ships. `multiple_assignments` counts every
    assignment, not only constructors: a use may refer to a non-legacy one.
    """
    fired: dict[BailCode, bool] = {
        "class_attr_binding": receiver.kind == "class_attr",
        "multiple_assignments": receiver.assignments > 1,
        "model_object_escapes": bool(receiver.escape_lines),
    }
    return next((code for code in ORDER if fired[code]), None)


def groups(result: Analysis) -> tuple[Group, ...]:
    """One group per binding, in analysis's order."""
    return tuple(
        Group(
            receiver=receiver,
            bail=refusal(receiver),
            lines=tuple(sorted({receiver.ctor_line, *receiver.use_lines})),
        )
        for receiver in result.receivers
    )


__all__ = ["BAILS", "ORDER", "RUNG", "Group", "groups", "refusal"]
