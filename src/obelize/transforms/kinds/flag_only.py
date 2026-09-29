"""`flag_only`: surfaces a pack refuses to rewrite; writes nothing, only attributes the rows.

The scan's refused sets are unions over the pack's `flag_only` changes, so `rule_id` is the only
link from a row to the change's message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

from obelize.models import (
    BailCode,
    ConfidenceReason,
    Edit,
    EditStatus,
    FindingKind,
    FlagOnlyPattern,
)

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from obelize.models import Finding
    from obelize.packs.schema import ChangeKind, FlagOnlyChange
    from obelize.transforms.base import RuleContext

# The codes this rule reports; the scan raises both at rung 1, the corpus grades the set.
BAILS: frozenset[BailCode] = frozenset({"attribute_removed", "flag_only_surface"})

# Kinds only a shape detector produces. Matched by reason alone, so a `mock.patch` target string is
# not also claimed for the surface it names.
_SHAPES: Final[frozenset[FindingKind]] = frozenset({"dynamic", "text_mention"})

# Confidence reason per pattern id: a table, since `sys_modules_stub` reports `dynamic_access`.
REASONS: Final[dict[FlagOnlyPattern, ConfidenceReason]] = {
    "dynamic_access": "dynamic_access",
    "mock_patch_target": "mock_patch_target",
    "sys_modules_stub": "dynamic_access",
}


class FlagOnly:
    kind: ClassVar[ChangeKind] = "flag_only"

    def __init__(self, change: FlagOnlyChange) -> None:
        self._id = change.id
        self._symbols = change.params.symbols
        self._attributes = frozenset(change.params.attributes)
        self._reasons = frozenset(REASONS[pattern] for pattern in change.params.patterns)

    @property
    def consumes(self) -> frozenset[str]:
        """Nothing: dropping a refused surface's import would edit a file the run refuses."""
        return frozenset()

    @property
    def client_readers(self) -> frozenset[str]:
        return frozenset()

    def claims(self, finding: Finding) -> bool:
        """Symbols by name prefix as `analysis._grade` does; attributes whole; shapes by reason."""
        # Only a `parse_error` has no symbol, and its bail matches neither branch below.
        symbol = finding.symbol or ""
        if finding.bail == "attribute_removed":
            return symbol in self._attributes
        if finding.bail != "flag_only_surface":
            return False
        if finding.kind in _SHAPES:
            return finding.confidence_reason in self._reasons
        return any(
            symbol == flagged or symbol.startswith(flagged + ".") for flagged in self._symbols
        )

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        """One edit per claimed row, carrying the status the scan gave it."""
        return tuple(
            Edit(
                path=context.path,
                line=finding.line,
                status=_status(finding),
                rule_id=self._id,
                reason=finding.bail,
            )
            for finding in context.plan.findings
            if self.claims(finding)
        )


def _status(finding: Finding) -> EditStatus:
    """The scan's status, narrowed for the type only: a claimed row is always withheld."""
    return "unsupported" if finding.scan_status == "unsupported" else "needs_review"


__all__ = ["BAILS", "REASONS", "FlagOnly"]
