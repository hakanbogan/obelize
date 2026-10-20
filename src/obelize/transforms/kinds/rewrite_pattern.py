"""`rewrite_pattern`: a call of a name, rewritten from the shape of its arguments.

`pydantic.parse_obj_as(T, v)` becomes `pydantic.TypeAdapter(T).validate_python(v)`, and
`user.dict(exclude=e)` becomes `user.model_dump(exclude=e)`, where the pack gives the two shapes
as templates (`obelize.pattern`). The scan found the call by the name it is of; this rule reads
whether its arguments have the shape `before` says and writes `after` over them. A call of another
shape is left for a person, since a pattern that did not cover it is no claim about it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

import libcst as cst

from obelize import pattern
from obelize.models import BailCode, Edit
from obelize.transforms.base import BailError
from obelize.transforms.tree import Tree

if TYPE_CHECKING:
    from obelize.models import Finding
    from obelize.packs.schema import ChangeKind, RewritePatternChange
    from obelize.transforms.base import RuleContext

# Codes this rule raises itself.
BAILS: frozenset[BailCode] = frozenset({"from_import_unmigrated_symbol", "pattern_unmatched"})


class RewritePattern:
    kind: ClassVar[ChangeKind] = "rewrite_pattern"

    def __init__(self, change: RewritePatternChange) -> None:
        self._id = change.id
        self._before = pattern.parse(change.params.before)
        self._after = pattern.parse(change.params.after)
        self._anchor = pattern.anchor(self._before, change.params.where)

    @property
    def consumes(self) -> frozenset[str]:
        """Nothing: the module stays imported, as the new spelling is written beside the old."""
        return frozenset()

    @property
    def client_readers(self) -> frozenset[str]:
        return frozenset()

    def claims(self, finding: Finding) -> bool:
        return finding.kind in {"call", "method_call"} and finding.symbol == self._anchor.symbol

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
        return tuple(self._edit(context, tree, finding) for finding in eligible)

    def _edit(self, context: RuleContext, tree: Tree, finding: Finding) -> Edit:
        try:
            call = self._call(tree, (finding.line, finding.column))
            replacement = pattern.place(self._rewrite(call, tree), tree.parent(call))
        except BailError as bail:
            return Edit(
                path=context.path,
                line=finding.line,
                status="needs_review",
                rule_id=self._id,
                reason=bail.reason,
            )
        context.rewrites.set(call, replacement)
        context.rewrites.keep_comments(tree.statement_of(call), call, replacement)
        return Edit(path=context.path, line=finding.line, status="auto", rule_id=self._id)

    def _call(self, tree: Tree, position: tuple[int, int]) -> cst.Call:
        """The call a finding names: of a member, the one its member name is the function of."""
        if self._anchor.receiver is None:
            return tree.call(position)
        attribute = tree.member(position)
        if attribute is None:
            # The member was called through the class's module (`lib.Shape.render(item, 3)`).
            raise BailError("pattern_unmatched")
        return cast("cst.Call", tree.parent(attribute))

    def _rewrite(self, call: cst.Call, tree: Tree) -> cst.BaseExpression:
        member = self._anchor.receiver is not None
        bound = pattern.match(self._before, call, spelled=member)
        if bound is None:
            raise BailError("pattern_unmatched")
        for name, expression in bound.items():
            # An expression written once is evaluated once, in the new call as in the old; one the
            # new call writes twice, or not at all, is run twice or never.
            if self._after.uses.get(name, 0) != 1 and not pattern.pure(expression):
                raise BailError("pattern_unmatched")
        if self._after.strings and tree.in_f_string(call):
            # A quote the new text writes may be the one the f-string is written with.
            raise BailError("pattern_unmatched")
        spelled: dict[str, cst.BaseExpression] = {}
        if pattern.new_names(self._after):
            # The new name is written beside the old: with whatever the file spelled the old one by.
            if not isinstance(call.func, cst.Attribute):
                raise BailError("from_import_unmigrated_symbol")
            spelled[self._anchor.symbol.rpartition(".")[0]] = call.func.value
        return pattern.build(self._after, bound, spelled)


__all__ = ["BAILS", "RewritePattern"]
