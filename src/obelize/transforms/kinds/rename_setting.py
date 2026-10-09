"""`rename_setting`: `module.setting = value` becomes `module.new_name = value` for a shared module.

Only a plain single-target assignment is rewritten. Any other use of the old name (a read, `+=`,
`del`, a tuple target) is `attribute_removed`: the new release has no attribute under it, so the
name would raise or, assigned, silently set nothing. `value_ends_with` is the new setting's own
demand of the value (`openai.base_url` joins routes without a separator): a string literal gets the
character, anything else is written `("%s" % (value,)).rstrip(c) + c`. That formats as the old
release's `"%s%s" % (setting, route)` did and names no builtin the file could have rebound.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import libcst as cst

from obelize.models import BailCode, Edit
from obelize.transforms.base import BailError, RuleContext
from obelize.transforms.tree import Position, Tree

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from obelize.models import Finding
    from obelize.packs.schema import ChangeKind, RenameSettingChange

# Codes this rule raises itself, graded as a set by the corpus.
BAILS: frozenset[BailCode] = frozenset({"alias_collision", "attribute_removed"})


class RenameSetting:
    kind: ClassVar[ChangeKind] = "rename_setting"

    def __init__(self, change: RenameSettingChange) -> None:
        self._id = change.id
        self._settings = change.params.settings
        self._tail = change.params.value_ends_with

    @property
    def consumes(self) -> frozenset[str]:
        """Nothing: the module stays imported, as the new release keeps it."""
        return frozenset()

    @property
    def client_readers(self) -> frozenset[str]:
        return frozenset()

    def claims(self, finding: Finding) -> bool:
        return finding.kind == "attribute" and finding.symbol in self._settings

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        eligible = sorted(
            (finding.line, finding.column, finding.symbol or "")
            for finding in context.plan.findings
            if finding.scan_status == "eligible" and self.claims(finding)
        )
        if not eligible:
            return ()
        tree = Tree(context)
        return tuple(self._edit(context, tree, *found) for found in eligible)

    def _edit(self, context: RuleContext, tree: Tree, line: int, column: int, symbol: str) -> Edit:
        try:
            self._rewrite(context, tree, (line, column), symbol)
        except BailError as bail:
            return Edit(
                path=context.path,
                line=line,
                status="needs_review",
                rule_id=self._id,
                reason=bail.reason,
            )
        return Edit(path=context.path, line=line, status="auto", rule_id=self._id)

    def _rewrite(self, context: RuleContext, tree: Tree, position: Position, symbol: str) -> None:
        target = tree.attribute(position, symbol)
        if target is None:
            # A from-imported name or a decorator: the old name read some way other than assigned.
            raise BailError("attribute_removed")
        assign = tree.parent(tree.parent(target))
        if not (
            isinstance(tree.parent(target), cst.AssignTarget)
            and isinstance(assign, cst.Assign)
            and len(assign.targets) == 1
        ):
            raise BailError("attribute_removed")
        new = self._settings[symbol]
        if tree.mentions(f"{symbol.rpartition('.')[0]}.{new}"):
            # The file sets or reads the new name itself, and that write would lack the ending.
            raise BailError("alias_collision")
        renamed = target.with_changes(attr=cst.Name(new))
        context.rewrites.set_statement(
            assign,
            assign.with_changes(
                targets=[assign.targets[0].with_changes(target=renamed)],
                value=self._value(assign.value),
            ),
        )

    def _value(self, value: cst.BaseExpression) -> cst.BaseExpression:
        tail = self._tail
        if tail is None:
            return value
        if isinstance(value, cst.SimpleString) and "b" not in value.prefix.lower():
            if str(value.evaluated_value).endswith(tail):
                return value
            return value.with_changes(value=value.value[: -len(value.quote)] + tail + value.quote)
        if isinstance(value, cst.Tuple | cst.Yield) and not value.lpar:
            value = value.with_changes(lpar=[cst.LeftParen()], rpar=[cst.RightParen()])
        character = cst.SimpleString(f'"{tail}"')
        formatted = cst.BinaryOperation(
            left=cst.SimpleString('"%s"'),
            operator=cst.Modulo(),
            right=cst.Tuple(
                [cst.Element(value=value)], lpar=[cst.LeftParen()], rpar=[cst.RightParen()]
            ),
            lpar=[cst.LeftParen()],
            rpar=[cst.RightParen()],
        )
        stripped = cst.Call(
            func=cst.Attribute(value=formatted, attr=cst.Name("rstrip")),
            args=[cst.Arg(value=character)],
        )
        return cst.BinaryOperation(left=stripped, operator=cst.Add(), right=character)


__all__ = ["BAILS", "RenameSetting"]
