"""`rename_symbol`: a name a submodule of a kept package defined, which the new release exports from
the package (`openai.error.RateLimitError` is `openai.RateLimitError`).

The submodule goes out of a reference, of `import openai.error` and of `from openai.error import X`.
Refused: a reference that is called, raised or derived from, since a new class is built from other
arguments; an `except` clause that reads an attribute of its bound name; and a clause that a handler
ahead of it may now catch for, because the new class derives from bases the old one did not
(`now_caught_by`) and a handler naming one of them, or one that cannot be told, was no obstacle.
"""

from __future__ import annotations

from itertools import takewhile
from typing import TYPE_CHECKING, ClassVar, cast

import libcst as cst
import libcst.matchers as m
from libcst.metadata import QualifiedNameSource

from obelize.models import BailCode, Edit
from obelize.transforms.base import BailError, RuleContext
from obelize.transforms.imports import dotted, dotted_name
from obelize.transforms.tree import Position, Tree

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from collections.abc import Iterator, Sequence

    from obelize.models import Finding
    from obelize.packs.schema import ChangeKind, RenameSymbolChange

# Codes this rule raises itself.
BAILS: frozenset[BailCode] = frozenset(
    {
        "alias_collision",
        "attribute_removed",
        "error_class_changed",
        "from_import_unmigrated_symbol",
    }
)


class RenameSymbol:
    kind: ClassVar[ChangeKind] = "rename_symbol"

    def __init__(self, change: RenameSymbolChange) -> None:
        self._id = change.id
        self._symbols = change.params.symbols
        self._bases = frozenset(change.params.now_caught_by)
        self._modules = frozenset(symbol.rpartition(".")[0] for symbol in self._symbols)

    @property
    def consumes(self) -> frozenset[str]:
        """Nothing: the package stays imported, as the new release keeps it."""
        return frozenset()

    @property
    def client_readers(self) -> frozenset[str]:
        return frozenset()

    def claims(self, finding: Finding) -> bool:
        if finding.kind == "import":
            return finding.symbol in self._modules
        return finding.kind in {"attribute", "call"} and finding.symbol in self._symbols

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
        position = (finding.line, finding.column)
        try:
            if finding.kind == "import":
                self._import(context, tree, position)
            else:
                self._reference(context, tree, finding, position)
        except BailError as bail:
            return Edit(
                path=context.path,
                line=finding.line,
                status="needs_review",
                rule_id=self._id,
                reason=bail.reason,
            )
        return Edit(path=context.path, line=finding.line, status="auto", rule_id=self._id)

    def _reference(
        self, context: RuleContext, tree: Tree, finding: Finding, position: Position
    ) -> None:
        if finding.kind == "call":
            raise BailError("error_class_changed")
        symbol = finding.symbol or ""
        # A resolved reference is a chain or a bound name; a string annotation is a mention only.
        node = cast(
            "cst.Attribute | cst.Name",
            tree.attribute(position, symbol) or tree.name(position, symbol),
        )
        parent = tree.parent(node)
        if isinstance(parent, cst.Raise) or (
            isinstance(parent, cst.Arg) and isinstance(tree.parent(parent), cst.ClassDef)
        ):
            raise BailError("error_class_changed")
        handler = _handler(tree, node)
        if handler is not None:
            self._check_handler(tree, handler)
        replacement = self._spelled(node, symbol)
        if replacement is not None:
            context.rewrites.set(node, replacement)

    def _spelled(self, node: cst.Attribute | cst.Name, symbol: str) -> cst.BaseExpression | None:
        """The reference as the new release spells it, or `None` where it is spelled so already."""
        old, new = symbol.rpartition(".")[2], self._symbols[symbol]
        if isinstance(node, cst.Name):
            # A bound name keeps its spelling unless its import was written without an alias.
            return cst.Name(new) if node.value == old != new else None
        if isinstance(node.value, cst.Attribute):
            return node.with_changes(value=node.value.value, attr=cst.Name(new))
        # An alias of the submodule: its import now binds the package.
        return node.with_changes(attr=cst.Name(new)) if old != new else None

    def _check_handler(
        self, tree: Tree, handler: cst.ExceptHandler | cst.ExceptStarHandler
    ) -> None:
        bound = handler.name.name if handler.name else None
        if isinstance(bound, cst.Name) and m.findall(
            handler.body, m.Attribute(value=m.Name(bound.value))
        ):
            # The new class has `status_code` and `body` where the old one had `http_status`.
            raise BailError("attribute_removed")
        clauses: Sequence[cst.ExceptHandler | cst.ExceptStarHandler] = cast(
            "cst.Try | cst.TryStar", tree.parent(handler)
        ).handlers
        if any(
            self._would_catch(tree, element)
            for earlier in takewhile(lambda other: other is not handler, clauses)
            if earlier.type is not None
            for element in _types(earlier.type)
        ):
            raise BailError("error_class_changed")

    def _would_catch(self, tree: Tree, element: cst.BaseExpression) -> bool:
        """Whether a handler naming `element` may be a base of the new class and was not of the old.

        A name bound in this file, or none that resolves, cannot be told from one.
        """
        names = tree.names(element)
        return not names or any(
            name.source is QualifiedNameSource.LOCAL or name.name in self._bases for name in names
        )

    def _import(self, context: RuleContext, tree: Tree, position: Position) -> None:
        line = next(
            (
                found
                for found in m.findall(tree.module, m.SimpleStatementLine())
                if isinstance(found, cst.SimpleStatementLine)
                and any(tree.start(small) == position for small in found.body)
            ),
            None,
        )
        if line is None:
            # In a one-line suite (`if ready: import openai.error`), which a replaced line is not.
            raise BailError("from_import_unmigrated_symbol")
        context.imports.replace(line, *(self._small(context, small) for small in line.body))

    def _small(self, context: RuleContext, small: cst.BaseSmallStatement) -> cst.BaseSmallStatement:
        if isinstance(small, cst.Import):
            return small.with_changes(names=[self._entry(entry) for entry in small.names])
        if (
            isinstance(small, cst.ImportFrom)
            and small.module is not None
            and not small.relative
            and not isinstance(small.names, cst.ImportStar)
        ):
            return self._from(context, small, dotted_name(small.module), small.names)
        return small

    def _entry(self, entry: cst.ImportAlias) -> cst.ImportAlias:
        """`import openai.error [as e]` binds the package, or the package as `e`, in its place."""
        module = dotted_name(entry.name)
        if module not in self._modules:
            return entry
        return entry.with_changes(name=dotted(module.rpartition(".")[0]))

    def _from(
        self,
        context: RuleContext,
        small: cst.ImportFrom,
        source: str,
        entries: Sequence[cst.ImportAlias],
    ) -> cst.ImportFrom:
        if source not in self._modules:
            # `from openai import error` binds the submodule, which has no spelling to move to.
            if any(f"{source}.{dotted_name(entry.name)}" in self._modules for entry in entries):
                raise BailError("from_import_unmigrated_symbol")
            return small
        renamed = []
        for entry in entries:
            name = dotted_name(entry.name)
            new = self._symbols.get(f"{source}.{name}")
            if new is None:
                raise BailError("from_import_unmigrated_symbol")
            if entry.asname is None and new != name and context.imports.bound(new):
                raise BailError("alias_collision")
            renamed.append(entry.with_changes(name=cst.Name(new)))
        return small.with_changes(module=dotted(source.rpartition(".")[0]), names=renamed)


def _handler(tree: Tree, node: cst.CSTNode) -> cst.ExceptHandler | cst.ExceptStarHandler | None:
    """The `except` clause `node` is, or is one of the elements of, the type of."""
    while isinstance(parent := tree.parent(node), cst.Element | cst.Tuple):
        node = parent
    return parent if isinstance(parent, cst.ExceptHandler | cst.ExceptStarHandler) else None


def _types(node: cst.BaseExpression) -> Iterator[cst.BaseExpression]:
    """The classes a handler names: the elements of a tuple, which may nest."""
    if isinstance(node, cst.Tuple):
        for element in node.elements:
            yield from _types(element.value)
    else:
        yield node


__all__ = ["BAILS", "RenameSymbol"]
