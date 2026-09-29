"""`rename_import`: legacy import statements, and reads of the `types` names they bound.

Call sites are left to the rules that replace them whole; atomicity withholds a file whose calls
nothing claims. An author's alias survives; the legacy module's own name does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

import libcst as cst
from libcst._metadata_dependent import LazyValue
from libcst.metadata import PositionProvider, QualifiedNameProvider

from obelize.models import Edit
from obelize.packs.schema import TYPES_SUBMODULE, RenameImportChange
from obelize.transforms.base import BailError, RuleContext
from obelize.transforms.imports import dotted_name, statement_for

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from collections.abc import Iterator

    from obelize.models import BailCode, Finding
    from obelize.packs.schema import ChangeKind, RenameImportParams

# A node's start: a finding's node and the prefix rewritten here begin at the same token.
Position = tuple[int, int]


@dataclass(frozen=True, slots=True)
class _Reference:
    """One read of a `types` name, and its new name."""

    node: cst.CSTNode
    mapped: str


@dataclass(frozen=True, slots=True)
class _Group:
    """An import statement and the reads of names it binds; they bail together."""

    statement: cst.SimpleStatementLine
    position: Position
    # Module-level names the statement binds, released for the rewrite to reuse.
    released: tuple[str, ...]
    references: dict[Position, _Reference]

    @property
    def positions(self) -> list[Position]:
        return [self.position, *self.references]


class RenameImport:
    kind: ClassVar[ChangeKind] = "rename_import"

    def __init__(self, change: RenameImportChange) -> None:
        self._id = change.id
        self._params: RenameImportParams = change.params
        self.from_module = change.params.from_module
        self._modules = frozenset(
            {change.params.from_module}
            | {f"{change.params.from_module}.{name}" for name in change.params.submodule_map}
        )
        self._types_module = f"{change.params.from_module}.{TYPES_SUBMODULE}"
        self._types_prefix = f"{self._types_module}."

    @property
    def consumes(self) -> frozenset[str]:
        return frozenset()

    @property
    def client_readers(self) -> frozenset[str]:
        return frozenset()

    def claims(self, finding: Finding) -> bool:
        symbol = finding.symbol or ""
        if finding.kind == "import":
            return symbol in self._modules
        if finding.kind in {"attribute", "call"}:
            return self.mapped(symbol) is not None
        return False

    def mapped(self, symbol: str) -> str | None:
        """The new name of the `types` symbol that `symbol` names or is a member of."""
        if not symbol.startswith(self._types_prefix):
            return None
        head = symbol[len(self._types_prefix) :].partition(".")[0]
        return self._params.types_symbol_map.get(head)

    def reference(self, symbol: str) -> str | None:
        """The new name only when `symbol` is the mapped symbol itself, so a member stays put."""
        mapped = self.mapped(symbol)
        if mapped is None or symbol != f"{self._types_prefix}{_leaf(symbol)}":
            return None
        return mapped

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        self._offer(context)
        eligible = {
            (finding.line, finding.column): finding
            for finding in context.plan.findings
            if finding.scan_status == "eligible" and self.claims(finding)
        }
        names = _Names(context, self)
        verdicts: dict[Position, BailCode | None] = {}
        for group in self._groups(names, eligible):
            try:
                self._rewrite(context, names, group)
            except BailError as bail:
                verdicts.update(dict.fromkeys(group.positions, bail.reason))
            else:
                verdicts.update(dict.fromkeys(group.positions, None))
        return self._edits(context, eligible, verdicts)

    def _offer(self, context: RuleContext) -> None:
        """Offer each submodule's import name to other rules, even if this one emits nothing."""
        for name, target in self._params.submodule_map.items():
            spare = self._params.types_alias_fallback if name == TYPES_SUBMODULE else None
            context.imports.offer(target, _leaf(target), spare)

    def _groups(self, names: _Names, eligible: dict[Position, Finding]) -> list[_Group]:
        """One group per eligible legacy import statement, in document order."""
        groups = []
        for statement in names.statements:
            line = names.position(statement)[0]
            position = next((key for key in eligible if key[0] == line), None)
            if position is None:
                continue
            released = _bound_by(statement)
            groups.append(
                _Group(
                    statement=statement,
                    position=position,
                    released=released,
                    references={
                        where: reference
                        for where, reference in names.references.items()
                        if where in eligible and names.root(reference.node) in released
                    },
                )
            )
        return groups

    def _rewrite(self, context: RuleContext, names: _Names, group: _Group) -> None:
        """Decide one group, or raise the bail that stops it."""
        context.imports.release(*group.released)
        emitted: list[cst.BaseSmallStatement] = []
        for small in group.statement.body:
            emitted.extend(self._small(context, names, small))
        context.imports.replace(group.statement, *emitted)
        if group.references:
            alias, extra = self._types_import(context, None)
            context.imports.append(group.statement, *extra)
            for reference in group.references.values():
                context.rewrites.set(reference.node, _read(reference.node, alias, reference.mapped))

    def _small(
        self, context: RuleContext, names: _Names, small: cst.BaseSmallStatement
    ) -> list[cst.BaseSmallStatement]:
        """What one small statement becomes; a non-import beside it survives on its own line."""
        if isinstance(small, cst.Import):
            return self._plain(context, names, small)
        if isinstance(small, cst.ImportFrom):
            return self._from(context, names, small)
        return [small]

    def _plain(
        self, context: RuleContext, names: _Names, small: cst.Import
    ) -> list[cst.BaseSmallStatement]:
        """`import <module>[.<submodule>] [as <alias>]`, possibly beside others."""
        kept: list[cst.ImportAlias] = []
        emitted: list[cst.BaseSmallStatement] = []
        for entry in small.names:
            target = dotted_name(entry.name)
            if target not in self._modules:
                kept.append(entry.with_changes(comma=cst.MaybeSentinel.DEFAULT))
            elif target == self._params.from_module:
                emitted.extend(self._module_import(context, names, _alias_of(entry)))
            else:
                emitted.extend(self._submodule_import(context, target, _alias_of(entry)))
        if kept:
            emitted.insert(0, small.with_changes(names=kept))
        return emitted

    def _from(
        self, context: RuleContext, names: _Names, small: cst.ImportFrom
    ) -> list[cst.BaseSmallStatement]:
        """`from <package> import ...`, in each of the three shapes that resolve."""
        if isinstance(small.names, cst.ImportStar):  # pragma: no cover - the scan bails first
            raise BailError("star_import")
        entries = list(small.names)
        source = "" if small.module is None else dotted_name(small.module)
        package, _, leaf = self._params.from_module.rpartition(".")
        if source == package:
            return self._from_package(context, names, small, entries, leaf)
        if source == self._params.from_module:
            return self._from_module(context, names, entries)
        if source != self._types_module:
            raise BailError("type_symbol_unmapped")
        return self._from_types(context, entries)

    def _from_package(
        self,
        context: RuleContext,
        names: _Names,
        small: cst.ImportFrom,
        entries: list[cst.ImportAlias],
        leaf: str,
    ) -> list[cst.BaseSmallStatement]:
        """`from google import generativeai`, possibly beside other names."""
        legacy = [item for item in entries if _named(item, leaf)]
        kept = [
            item.with_changes(comma=cst.MaybeSentinel.DEFAULT)
            for item in entries
            if not _named(item, leaf)
        ]
        emitted = list(self._module_import(context, names, _alias_of(legacy[0])))
        if kept:
            emitted.insert(0, small.with_changes(names=kept))
        return emitted

    def _from_module(
        self, context: RuleContext, names: _Names, entries: list[cst.ImportAlias]
    ) -> list[cst.BaseSmallStatement]:
        """`from <module> import <name>`: a submodule, a consumed symbol, or a bail.

        A name a running rule consumes is dropped, not bailed, and becomes the module import that
        rule's new call is reached through.
        """
        emitted: list[cst.BaseSmallStatement] = []
        swallowed = False
        for entry in entries:
            name = entry.name
            if not isinstance(name, cst.Name):  # pragma: no cover - an alias names a name
                raise BailError("from_import_unmigrated_symbol")
            if f"{self._params.from_module}.{name.value}" in context.consumed:
                swallowed = True
            elif name.value in self._params.submodule_map:
                target = f"{self._params.from_module}.{name.value}"
                emitted.extend(self._submodule_import(context, target, _alias_of(entry)))
            else:
                raise BailError("from_import_unmigrated_symbol")
        if swallowed:
            emitted.extend(self._module_import(context, names, None))
        return emitted

    def _from_types(
        self, context: RuleContext, entries: list[cst.ImportAlias]
    ) -> list[cst.BaseSmallStatement]:
        """`from <module>.types import <symbol>`: the symbols become reads."""
        for entry in entries:
            name = entry.name
            if not isinstance(name, cst.Name) or name.value not in self._params.types_symbol_map:
                raise BailError("type_symbol_unmapped")
        return list(self._types_import(context, None)[1])

    def _module_import(
        self, context: RuleContext, names: _Names, author: str | None
    ) -> list[cst.BaseSmallStatement]:
        """The new module's import, only if a legacy reference survives this rule."""
        if not names.survivors:
            return []
        alias = author if author is not None else context.imports.take(self._params.default_alias)
        if alias is None:
            raise BailError("alias_collision")
        context.imports.bind(self._params.to_module, alias)
        return [statement_for(self._params.to_module, alias)]

    def _types_import(
        self, context: RuleContext, author: str | None
    ) -> tuple[str, list[cst.BaseSmallStatement]]:
        target = self._params.submodule_map[TYPES_SUBMODULE]
        return self._bind(context, target, author, self._params.types_alias_fallback)

    def _submodule_import(
        self, context: RuleContext, target: str, author: str | None
    ) -> list[cst.BaseSmallStatement]:
        moved = self._params.submodule_map[target.rpartition(".")[2]]
        spare = self._params.types_alias_fallback if moved == self._types_target else None
        return self._bind(context, moved, author, spare)[1]

    @property
    def _types_target(self) -> str:
        return self._params.submodule_map[TYPES_SUBMODULE]

    def _bind(
        self, context: RuleContext, target: str, author: str | None, spare: str | None
    ) -> tuple[str, list[cst.BaseSmallStatement]]:
        """The name `target` is reached through, and its import unless already bound."""
        bound = context.imports.binding(target)
        if bound is not None:
            return bound, []
        alias = author if author is not None else context.imports.take(_leaf(target), spare)
        if alias is None:
            raise BailError("alias_collision")
        context.imports.bind(target, alias)
        return alias, [statement_for(target, alias)]

    def _edits(
        self,
        context: RuleContext,
        eligible: dict[Position, Finding],
        verdicts: dict[Position, BailCode | None],
    ) -> tuple[Edit, ...]:
        """One row per claimed finding with its group's verdict, in document order.

        A finding with no group is bound outside this file (`star_import`, `module_alias_rebound`),
        which the scan already withholds.
        """
        return tuple(
            Edit(
                path=context.path,
                line=finding.line,
                status="auto" if verdicts[position] is None else "needs_review",
                rule_id=self._id,
                reason=verdicts[position],
            )
            for position, finding in sorted(eligible.items())
            if position in verdicts
        )


class _Names:
    """One resolve pass: the legacy import statements, and what resolves to what."""

    def __init__(self, context: RuleContext, rule: RenameImport) -> None:
        context.wrapper.resolve_many([QualifiedNameProvider, PositionProvider])
        self._qnp = context.wrapper.resolve(QualifiedNameProvider)
        self._pos = context.wrapper.resolve(PositionProvider)
        self._module = context.wrapper.module
        self.statements = _legacy_statements(context.wrapper.module, rule.from_module)
        legacy: list[cst.CSTNode] = []
        self.references: dict[Position, _Reference] = {}
        for node in self._qnp:
            symbol = self.qualified(node)
            if not _under(symbol, rule.from_module):
                continue
            legacy.append(node)
            mapped = rule.reference(symbol)
            if mapped is not None:
                self.references[self.position(node)] = _Reference(node=node, mapped=mapped)
        self.survivors = _survivors(legacy, [row.node for row in self.references.values()])

    def position(self, node: cst.CSTNode) -> Position:
        start = self._pos[node].start
        return (start.line, start.column)

    def qualified(self, node: cst.CSTNode) -> str:
        """The one qualified name, or `""` if none or several (`conditional_binding`, withheld)."""
        value = self._qnp.get(node, ())
        names = {name.name for name in (value() if isinstance(value, LazyValue) else value)}
        return names.pop() if len(names) == 1 else ""

    def root(self, node: cst.CSTNode) -> str:
        """The first segment of how `node` is spelled in the source."""
        if isinstance(node, cst.SimpleString):
            value = node.evaluated_value
            text = value if isinstance(value, str) else ""
        else:
            text = self._module.code_for_node(node)
        return text.partition(".")[0].strip()


def _read(node: cst.CSTNode, alias: str, mapped: str) -> cst.BaseExpression:
    """`<alias>.<mapped>`, in the shape the node it replaces was written in."""
    if isinstance(node, cst.SimpleString):
        return cst.SimpleString(f"{node.prefix}{node.quote}{alias}.{mapped}{node.quote}")
    return cst.Attribute(value=cst.Name(alias), attr=cst.Name(mapped))


def _legacy_statements(module: cst.Module, from_module: str) -> list[cst.SimpleStatementLine]:
    """Every statement line that imports the legacy module, in document order.

    A walk, not `module.body`: an `if TYPE_CHECKING:` import is module scope too.
    Function-local imports it also finds are withheld by the scan (`local_import`).
    """
    finder = _Statements(from_module)
    module.visit(finder)
    return finder.found


class _Statements(cst.CSTVisitor):
    def __init__(self, from_module: str) -> None:
        super().__init__()
        self._from = from_module
        self._package, _, self._leaf = from_module.rpartition(".")
        self.found: list[cst.SimpleStatementLine] = []

    def visit_SimpleStatementLine(  # noqa: N802 - libcst dispatches on the node name
        self, node: cst.SimpleStatementLine
    ) -> bool:
        if any(self._touches(small) for small in node.body):
            self.found.append(node)
        return False

    def _touches(self, small: cst.BaseSmallStatement) -> bool:
        if isinstance(small, cst.Import):
            return any(_under(dotted_name(entry.name), self._from) for entry in small.names)
        if not isinstance(small, cst.ImportFrom) or small.module is None:
            return False
        source = dotted_name(small.module)
        if _under(source, self._from):
            return True
        if source != self._package or isinstance(small.names, cst.ImportStar):
            return False
        return any(_named(entry, self._leaf) for entry in small.names)


def _survivors(legacy: list[cst.CSTNode], dissolved: list[cst.CSTNode]) -> bool:
    """Whether any reference to the legacy module outlives this rule's rewrites.

    Nodes inside or above a rewritten chain do not count. Read off the tree, not the plan:
    `genai.__version__` has no pack symbol but still needs the import.
    """
    roots = {id(node) for node in dissolved}
    inside = {key for node in dissolved for key in _subtree(node)}
    return any(id(node) not in inside and not (_subtree(node) & roots) for node in legacy)


def _subtree(node: cst.CSTNode) -> set[int]:
    return {id(node), *(key for child in node.children for key in _subtree(child))}


def _bound_by(statement: cst.SimpleStatementLine) -> tuple[str, ...]:
    names: list[str] = []
    for small in statement.body:
        if isinstance(small, (cst.Import, cst.ImportFrom)):
            names.extend(_binds(small))
    return tuple(names)


def _binds(small: cst.Import | cst.ImportFrom) -> Iterator[str]:
    if isinstance(small.names, cst.ImportStar):  # pragma: no cover - the scan bails first
        return
    for entry in small.names:
        alias = _alias_of(entry)
        if alias is not None:
            yield alias
        elif isinstance(small, cst.Import):
            yield dotted_name(entry.name).partition(".")[0]
        else:
            yield dotted_name(entry.name)


def _alias_of(entry: cst.ImportAlias) -> str | None:
    if entry.asname is None:
        return None
    name = entry.asname.name
    return name.value if isinstance(name, cst.Name) else None  # pragma: no branch


def _named(entry: cst.ImportAlias, value: str) -> bool:
    return isinstance(entry.name, cst.Name) and entry.name.value == value


def _under(symbol: str, module: str) -> bool:
    return symbol == module or symbol.startswith(f"{module}.")


def _leaf(path: str) -> str:
    return path.rpartition(".")[2]
