"""`rename_member`: a member of a class that the new release spells another way.

`user.dict()` becomes `user.model_dump()` where the scan typed `user` as an instance of a class the
pack names, or of one that derives from it. Only the member's name changes: the pack asserts that
the member takes the arguments it took, and a member the repository's own class defines is refused
at the scan, since the new name would run another function.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

import libcst as cst

from obelize.models import Edit
from obelize.transforms.tree import Tree

if TYPE_CHECKING:
    from obelize.models import Finding
    from obelize.packs.schema import ChangeKind, RenameMemberChange
    from obelize.transforms.base import RuleContext


class RenameMember:
    kind: ClassVar[ChangeKind] = "rename_member"

    def __init__(self, change: RenameMemberChange) -> None:
        self._id = change.id
        self._members = change.params.members

    @property
    def consumes(self) -> frozenset[str]:
        """Nothing: the class stays imported, as the new release keeps it."""
        return frozenset()

    @property
    def client_readers(self) -> frozenset[str]:
        return frozenset()

    def claims(self, finding: Finding) -> bool:
        return (
            finding.kind in {"attribute", "call", "method_call"} and finding.symbol in self._members
        )

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        eligible = sorted(
            (
                finding
                for finding in context.plan.findings
                if finding.scan_status == "eligible" and self.claims(finding)
            ),
            key=lambda finding: (finding.line, finding.column),
        )
        if not eligible:
            return ()
        tree = Tree(context)
        for finding in eligible:
            symbol = finding.symbol or ""
            position = (finding.line, finding.column)
            # A member read off an instance starts at its own name; one read through the class's
            # module (`pydantic.BaseModel.dict`) starts where the chain does.
            node = cast("cst.Attribute", tree.member(position) or tree.attribute(position, symbol))
            context.rewrites.rename_member(node, self._members[symbol])
        return tuple(
            Edit(path=context.path, line=finding.line, status="auto", rule_id=self._id)
            for finding in eligible
        )


__all__ = ["RenameMember"]
