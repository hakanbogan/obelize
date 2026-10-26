"""One module's import changes, collected from every rule and applied once by `finish()`.

Emitted statements replace the legacy statement that caused them, in place, keeping its comments;
a fresh import is anchored only to one that runs. `offer()`/`require()` let one rule own a
submodule's names and any other ask by path, so the file gets one `from google.genai import types`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, cast

import libcst as cst
from libcst.helpers import get_full_name_for_node
from libcst.metadata import MetadataWrapper, ParentNodeProvider, PositionProvider, ScopeProvider

if TYPE_CHECKING:
    from collections.abc import Collection

    from libcst.metadata import Scope

    from obelize.models import BailCode


def bound_names(wrapper: MetadataWrapper) -> frozenset[str]:
    """Every name bound in any scope, so a name any scope shadows is never introduced.

    Dotted entries (`google.generativeai`) are kept: they cannot collide with an alias.
    """
    # Typed `Scope | None`, but no node has been seen to map to `None`.
    scopes = cast("Collection[Scope]", set(wrapper.resolve(ScopeProvider).values()))
    return frozenset(assignment.name for scope in scopes for assignment in scope.assignments)


class _Rebound(cst.CSTVisitor):
    """What `ScopeProvider` leaves out: the names a `case` captures and a `del` unbinds, and whether
    a star import may bind any name at all."""

    def __init__(self) -> None:
        super().__init__()
        self.names: list[str] = []
        self.star = False

    def on_visit(self, node: cst.CSTNode) -> bool:
        if isinstance(node, cst.MatchAs | cst.MatchStar):
            self._bind(node.name)
        elif isinstance(node, cst.MatchMapping):
            self._bind(node.rest)
        elif isinstance(node, cst.Del):
            self._unbind(node.target)
        elif isinstance(node, cst.ImportFrom):
            self.star = self.star or isinstance(node.names, cst.ImportStar)
        return True

    def _bind(self, name: cst.Name | None) -> None:
        if name is not None:
            self.names.append(name.value)

    def _unbind(self, target: cst.BaseExpression) -> None:
        if isinstance(target, cst.Name):
            self.names.append(target.value)
        elif isinstance(target, cst.Tuple | cst.List):
            for element in target.elements:
                self._unbind(element.value)


@dataclass(slots=True)
class _Anchor:
    """One legacy statement, and the statements that take its place."""

    # Held so the node stays alive: the plan is keyed by `id()`.
    statement: cst.SimpleStatementLine
    nodes: list[cst.BaseSmallStatement] = field(default_factory=list)


class ImportPlan:
    """The import changes one file's rules have asked for, not yet applied."""

    def __init__(self, wrapper: MetadataWrapper) -> None:
        self._wrapper = wrapper
        self._rebound = _Rebound()
        wrapper.module.visit(self._rebound)
        self._bound = {*bound_names(wrapper), *self._rebound.names}
        self._parents = wrapper.resolve(ParentNodeProvider)
        self._anchors: dict[int, _Anchor] = {}
        self._bindings: dict[str, str] = {}
        self._offers: dict[str, tuple[str, str | None]] = {}
        self._first: cst.SimpleStatementLine | None = None

    def release(self, *names: str) -> None:
        """Free the names a replaced statement binds, so its rewrite does not collide with it."""
        self._bound.difference_update(names)

    def bound(self, name: str) -> bool:
        """Whether `name` is bound anywhere in the file, or reserved by this plan."""
        return name in self._bound

    def take(self, prefer: str, fallback: str | None = None) -> str | None:
        """Reserve the first free name, or `None` when every candidate is taken."""
        for candidate in (prefer, fallback):
            if candidate is not None and candidate not in self._bound:
                self._bound.add(candidate)
                return candidate
        return None

    def bind(self, module_path: str, name: str) -> None:
        """Record that this file now reaches `module_path` through `name`."""
        self._bindings[module_path] = name

    def binding(self, module_path: str) -> str | None:
        """The name this plan has already bound `module_path` to, if any."""
        return self._bindings.get(module_path)

    def rebound(self, name: str) -> bool:
        """Whether a `case` capture or a `del` binds `name` somewhere in the file."""
        return name in self._rebound.names

    @property
    def starred(self) -> bool:
        """Whether the file has a star import, which may bind any name where it stands."""
        return self._rebound.star

    def anchor(self, line: int) -> bool:
        """Whether fresh imports have a line to follow: the one a rule replaced, else the last
        top-level import above `line`, kept as it is. It is above the first use, so the name it
        binds is bound where the use runs; with none, a file imports only inside functions."""
        if self._first is None and (lines := self._imports_above(line)):
            self.replace(lines[-1], *lines[-1].body)
        return self._first is not None

    def found(self, module_path: str, line: int) -> str | None:
        """The name a top-level import above `line` binds `module_path` to, as the file spells it.

        Only a name the file binds once: another binding of it (a parameter, a local, a second
        import) could stand in its place where `line` is.
        """
        for statement in self._imports_above(line):
            for small in statement.body:
                for path, spelled in _bindings(small):
                    if path == module_path and self._counts[spelled.partition(".")[0]] == 1:
                        return spelled
        return None

    def offer(self, module_path: str, prefer: str, fallback: str | None = None) -> None:
        """Register the names `module_path` may take, whether or not it is ever emitted."""
        self._offers[module_path] = (prefer, fallback)

    def require(self, module_path: str) -> str | None:
        """The name this file reaches `module_path` by, introducing it if needed; else `None`.

        `None` when no candidate is free, nothing that runs was replaced to anchor it, or the module
        is bound only under `TYPE_CHECKING`; `refusal` says which.
        """
        bound = self._bindings.get(module_path)
        if bound is not None:
            return None if self._typing_only(module_path, bound) else bound
        offer = self._offers.get(module_path)
        if offer is None or self._first is None:
            return None
        alias = self.take(*offer)
        if alias is None:
            return None
        self.bind(module_path, alias)
        self.append(self._first, statement_for(module_path, alias))
        return alias

    def reaches(self, module_path: str, statement: cst.SimpleStatementLine) -> bool:
        """Whether the name bound to `module_path` is also bound where `statement`'s code runs.

        It is when `statement` emitted that import itself, or the import sits in the module body;
        one in another branch or a `TYPE_CHECKING` block does not reach it.
        """
        emitted = _code(statement_for(module_path, self._bindings[module_path]))
        return any(
            anchor.statement is statement or self._runs(anchor.statement)
            for anchor in self._anchors.values()
            if any(_code(node) == emitted for node in anchor.nodes)
        )

    def refusal(self, module_path: str) -> BailCode:
        """Why `require` gave `None`, as the bail a rule reports.

        `types_import_typing_only` when only code that never runs binds or could anchor it.
        """
        if module_path in self._bindings or (self._anchors and self._first is None):
            return "types_import_typing_only"
        return "alias_collision"

    def replace(self, statement: cst.SimpleStatementLine, *nodes: cst.BaseSmallStatement) -> None:
        """Say what `statement` becomes (no nodes: deleted); the first that runs anchors imports."""
        if self._first is None and self._runs(statement):
            self._first = statement
        self._anchor(statement).nodes = list(nodes)

    def append(self, statement: cst.SimpleStatementLine, *nodes: cst.BaseSmallStatement) -> None:
        """Add statements after whatever `statement` was already replaced by."""
        self._anchor(statement).nodes.extend(nodes)

    def lines_for(
        self, original: cst.SimpleStatementLine, updated: cst.SimpleStatementLine
    ) -> list[cst.SimpleStatementLine] | None:
        """The lines replacing `original` (empty: deleted), or `None` if it is not anchored.

        The first is built from `updated`, keeping its blank lines and comments; the rest follow it.
        """
        anchor = self._anchors.get(id(original))
        if anchor is None:
            return None
        return [
            updated.with_changes(body=[_bare(node)])
            if index == 0
            else cst.SimpleStatementLine(body=[_bare(node)])
            for index, node in enumerate(anchor.nodes)
        ]

    @cached_property
    def _counts(self) -> Counter[str]:
        """How many times each name is bound, in any scope."""
        scopes = cast("Collection[Scope]", set(self._wrapper.resolve(ScopeProvider).values()))
        return Counter(
            [
                *(assignment.name for scope in scopes for assignment in scope.assignments),
                *self._rebound.names,
            ]
        )

    def _imports_above(self, line: int) -> list[cst.SimpleStatementLine]:
        """The module-level lines of one import that end before `line` starts, in order."""
        where = self._wrapper.resolve(PositionProvider)
        return [
            statement
            for statement in self._wrapper.module.body
            if isinstance(statement, cst.SimpleStatementLine)
            and len(statement.body) == 1
            and isinstance(statement.body[0], cst.Import | cst.ImportFrom)
            and where[statement].end.line <= line
        ]

    def _runs(self, statement: cst.SimpleStatementLine) -> bool:
        """Whether `statement` is directly in the module's body, where it runs on import."""
        return isinstance(self._parents.get(statement), cst.Module)

    def _typing_only(self, module_path: str, name: str) -> bool:
        """Whether every statement this plan emitted to bind `name` sits where nothing runs."""
        emitted = _code(statement_for(module_path, name))
        return not any(
            self._runs(anchor.statement)
            for anchor in self._anchors.values()
            if any(_code(node) == emitted for node in anchor.nodes)
        )

    def _anchor(self, statement: cst.SimpleStatementLine) -> _Anchor:
        return self._anchors.setdefault(id(statement), _Anchor(statement))


def _bindings(small: cst.BaseSmallStatement) -> list[tuple[str, str]]:
    """Each importable path a statement binds, with the name that reaches it: `import a.b` reaches
    `a.b` as `a.b`, `import a as x` reaches `a` as `x`, `from a import b as y` reaches `a.b` as
    `y`. A relative import and a star import reach no path."""
    if isinstance(small, cst.Import):
        return [
            (path, _spelled(entry, path))
            for entry in small.names
            if (path := get_full_name_for_node(entry.name))
        ]
    if isinstance(small, cst.ImportFrom) and not small.relative:
        # Absolute, so the module is named; a star import has no names.
        module = get_full_name_for_node(cast("cst.Name | cst.Attribute", small.module))
        entries = () if isinstance(small.names, cst.ImportStar) else small.names
        return [
            (f"{module}.{name}", _spelled(entry, name))
            for entry in entries
            if (name := get_full_name_for_node(entry.name))
        ]
    return []


def _spelled(entry: cst.ImportAlias, default: str) -> str:
    """The name an alias binds: the one after `as`, else the one it imports."""
    return (get_full_name_for_node(entry.asname.name) if entry.asname else None) or default


def statement_for(module_path: str, name: str) -> cst.BaseSmallStatement:
    """`from <package> import <leaf> [as <name>]` (the new SDK's idiom), or a plain import."""
    package, _, leaf = module_path.rpartition(".")
    asname = None if leaf == name else cst.AsName(name=cst.Name(name))
    if not package:
        return cst.Import(names=[cst.ImportAlias(name=cst.Name(module_path), asname=asname)])
    return cst.ImportFrom(
        module=dotted(package),
        names=[cst.ImportAlias(name=cst.Name(leaf), asname=asname)],
    )


def _code(node: cst.BaseSmallStatement) -> str:
    return cst.Module(body=[]).code_for_node(node)


def dotted(path: str) -> cst.Attribute | cst.Name:
    """`a.b.c` as the left-nested `Attribute` chain libcst wants."""
    head, _, tail = path.partition(".")
    node: cst.Attribute | cst.Name = cst.Name(head)
    while tail:
        segment, _, tail = tail.partition(".")
        node = cst.Attribute(value=node, attr=cst.Name(segment))
    return node


def _bare(node: cst.BaseSmallStatement) -> cst.BaseSmallStatement:
    """One statement per line, so a semicolon carried over from the source goes."""
    return node.with_changes(semicolon=cst.MaybeSentinel.DEFAULT)
