"""The rule protocol: what a rule reads (`RuleContext`), records (`Rewrites`) and reports.

A rule claims only what it would rewrite, raises `BailError` per group and carries on, decides a
group's every refusal before recording any of it, and records rather than rewrites: `finish()`
applies all rules in one pass. Records are keyed by node identity, hence `unsafe_skip_copy=True`;
over a copied tree every rewrite is a silent no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

import libcst as cst
from libcst.metadata import MetadataWrapper

from obelize.packs.schema import Layout
from obelize.transforms.imports import ImportPlan

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from collections.abc import Sequence

    from obelize.models import BailCode, Edit, Finding, ImpactPlan, ScanSpec
    from obelize.packs.schema import ChangeKind


class BailError(Exception):
    """One group a rule will not rewrite; the closed-vocabulary code is the whole message."""

    def __init__(self, reason: BailCode) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(slots=True)
class ClientBinding:
    """The client expression (`client`, `self.client`, ...) later rules call on, or the bail.

    A later rule reports `bail` rather than a second defect of its own.
    """

    expression: str | None = None
    bail: BailCode | None = None


@dataclass(frozen=True, slots=True)
class RuleContext:
    """One file as a rule sees it; `module is wrapper.module`, which only `build()` arranges."""

    path: str
    module: cst.Module
    wrapper: MetadataWrapper
    plan: ImpactPlan
    # The projection the plan was graded against, so shared questions get the planner's answer.
    spec: ScanSpec
    imports: ImportPlan
    rewrites: Rewrites
    # The user's line width, the one layout number that is not Obelize's.
    layout: Layout
    # Legacy symbols the running rules replace whole; an import binding only these can go.
    consumed: frozenset[str]
    # Free functions the running rules rewrite as client calls, which `needs_client` misses.
    client_readers: frozenset[str]
    # Filled in by whichever rule introduces the client.
    client: ClientBinding

    @classmethod
    def build(
        cls,
        plan: ImpactPlan,
        module: cst.Module,
        spec: ScanSpec,
        rules: Sequence[Rule] = (),
        layout: Layout | None = None,
    ) -> RuleContext:
        """The only constructor; `consumed` comes from `rules`, the ones that will run here."""
        wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
        return cls(
            path=str(plan.path),
            module=module,
            wrapper=wrapper,
            plan=plan,
            spec=spec,
            imports=ImportPlan(wrapper),
            rewrites=Rewrites(),
            layout=layout or Layout(),
            consumed=frozenset().union(*(rule.consumes for rule in rules)),
            client_readers=frozenset().union(*(rule.client_readers for rule in rules)),
            client=ClientBinding(),
        )


class Rewrites:
    """Every node the rules replace, keyed by identity: a position moves with any line above."""

    def __init__(self) -> None:
        self._by_id: dict[int, cst.BaseExpression] = {}
        self._statements: dict[int, cst.BaseSmallStatement] = {}
        self._dropped: set[int] = set()
        self._leading: dict[int, tuple[cst.EmptyLine, ...]] = {}

    def set(self, node: cst.CSTNode, replacement: cst.BaseExpression) -> None:
        self._by_id[id(node)] = replacement

    def get(self, node: cst.CSTNode) -> cst.BaseExpression | None:
        return self._by_id.get(id(node))

    def set_statement(
        self, node: cst.BaseSmallStatement, replacement: cst.BaseSmallStatement
    ) -> None:
        """Replace a small statement, even with another type, keeping the line and its comments."""
        self._statements[id(node)] = replacement

    def statement(self, node: cst.BaseSmallStatement) -> cst.BaseSmallStatement | None:
        return self._statements.get(id(node))

    def drop(self, node: cst.BaseSmallStatement) -> None:
        """Delete a small statement; an emptied line goes too, with its leading blank lines."""
        self._dropped.add(id(node))

    def dropped(self, node: cst.BaseSmallStatement) -> bool:
        return id(node) in self._dropped

    def lead(self, node: cst.CSTNode, lines: tuple[cst.EmptyLine, ...]) -> None:
        """Move a deleted statement's leading lines and comments onto `node` or its footer."""
        self._leading[id(node)] = self._leading.get(id(node), ()) + lines

    def leading(self, node: cst.CSTNode) -> tuple[cst.EmptyLine, ...]:
        return self._leading.get(id(node), ())


class Rule(Protocol):
    """The protocol `transforms/registry.py` maps a pack's `kind` onto."""

    kind: ClassVar[ChangeKind]

    @property
    def consumes(self) -> frozenset[str]:
        """Legacy symbols this rule replaces whole, so their import can go."""

    @property
    def client_readers(self) -> frozenset[str]:
        """Legacy free functions this rule writes as calls on the client."""

    def claims(self, finding: Finding) -> bool:
        """Whether this rule is the one that would rewrite `finding`."""

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        """Record what this rule claims in `context`, and report what it did."""


def finish(context: RuleContext) -> cst.Module:
    """Write every recorded change in one pass; a second would find none of the recorded nodes."""
    return context.module.visit(_Apply(context))


def _led(
    node: cst.CSTNode | cst.RemovalSentinel | cst.FlattenSentinel[cst.CSTNodeT],
    lines: tuple[cst.EmptyLine, ...],
) -> cst.CSTNode | cst.RemovalSentinel | cst.FlattenSentinel[cst.CSTNodeT]:
    """`node` with `lines` in front of it, wherever that node keeps its lines."""
    if isinstance(node, (cst.Module, cst.IndentedBlock)):
        # Before the block's own footer: the deleted statement preceded those lines.
        return node.with_changes(footer=[*lines, *node.footer])
    if isinstance(node, (cst.SimpleStatementLine, cst.BaseCompoundStatement)):
        # After the statement's own leading lines, so the moved ones sit directly above it.
        return node.with_changes(leading_lines=[*node.leading_lines, *lines])
    return node  # pragma: no cover - a rule only ever leads a statement or a block


class _Apply(cst.CSTTransformer):
    """The one pass: the import statements, and the reads the rules replaced."""

    def __init__(self, context: RuleContext) -> None:
        super().__init__()
        self._imports = context.imports
        self._rewrites = context.rewrites

    def on_leave(
        self, original_node: cst.CSTNodeT, updated_node: cst.CSTNodeT
    ) -> cst.CSTNodeT | cst.RemovalSentinel | cst.FlattenSentinel[cst.CSTNodeT]:
        """The dispatch, then a deleted statement's lines onto whatever comes next, of any type."""
        result = super().on_leave(original_node, updated_node)
        lines = self._rewrites.leading(original_node)
        if not lines:
            return result
        # `with_changes` keeps the node's type; mypy cannot see that through the narrowing.
        return cast("cst.CSTNodeT", _led(result, lines))

    def leave_SimpleStatementLine(  # noqa: N802 - libcst dispatches on the node name
        self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine
    ) -> cst.SimpleStatementLine | cst.FlattenSentinel[cst.BaseStatement] | cst.RemovalSentinel:
        lines = self._imports.lines_for(original_node, updated_node)
        if lines is not None:
            if not lines:
                return cst.RemoveFromParent()
            if len(lines) == 1:
                return lines[0]
            return cst.FlattenSentinel(lines)
        kept = self._kept(original_node, updated_node)
        if kept is None:
            return updated_node
        if not kept:
            return cst.RemoveFromParent()
        return updated_node.with_changes(body=kept)

    def leave_SimpleStatementSuite(  # noqa: N802 - libcst dispatches on the node name
        self, original_node: cst.SimpleStatementSuite, updated_node: cst.SimpleStatementSuite
    ) -> cst.SimpleStatementSuite:
        """Deletions in a one-line suite (`if ready: MODEL = ...`); libcst writes `pass` if empty.

        Without it the statement silently survives while its uses are rewritten and reported `auto`.
        """
        kept = self._kept(original_node, updated_node)
        if kept is None:
            return updated_node
        return updated_node.with_changes(body=kept)

    def _kept(
        self,
        original_node: cst.SimpleStatementLine | cst.SimpleStatementSuite,
        updated_node: cst.SimpleStatementLine | cst.SimpleStatementSuite,
    ) -> list[cst.BaseSmallStatement] | None:
        """The body without its dropped statements, or `None` (the cheap common case) if none.

        Bodies align one to one; the last survivor's semicolon belonged to a dropped statement.
        """
        kept = [
            new
            for old, new in zip(original_node.body, updated_node.body, strict=True)
            if not self._rewrites.dropped(old)
        ]
        if len(kept) == len(updated_node.body):
            return None
        if kept:
            kept[-1] = kept[-1].with_changes(semicolon=cst.MaybeSentinel.DEFAULT)
        return kept

    def leave_Expr(  # noqa: N802 - libcst dispatches on the node name
        self, original_node: cst.Expr, updated_node: cst.Expr
    ) -> cst.BaseSmallStatement:
        """A replaced expression statement, visited again: other rules' swaps inside it apply."""
        replacement = self._rewrites.statement(original_node)
        if replacement is None:
            return updated_node
        rewritten = replacement.visit(self)
        if not isinstance(rewritten, cst.BaseSmallStatement):  # pragma: no cover - nothing removes
            return updated_node
        return rewritten

    def leave_Call(  # noqa: N802 - libcst dispatches on the node name
        self, original_node: cst.Call, updated_node: cst.Call
    ) -> cst.BaseExpression:
        """A call a rule replaced, visited again as in `leave_Expr`; it never contains itself."""
        replacement = self._rewrites.get(original_node)
        if replacement is None:
            return updated_node
        rewritten = replacement.visit(self)
        if not isinstance(rewritten, cst.BaseExpression):  # pragma: no cover - nothing removes
            return updated_node
        return rewritten

    def leave_Name(  # noqa: N802 - libcst dispatches on the node name
        self, original_node: cst.Name, updated_node: cst.Name
    ) -> cst.BaseExpression:
        return self._rewrites.get(original_node) or updated_node

    def leave_Attribute(  # noqa: N802 - libcst dispatches on the node name
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        return self._rewrites.get(original_node) or updated_node

    def leave_SimpleString(  # noqa: N802 - libcst dispatches on the node name
        self, original_node: cst.SimpleString, updated_node: cst.SimpleString
    ) -> cst.BaseExpression:
        return self._rewrites.get(original_node) or updated_node
