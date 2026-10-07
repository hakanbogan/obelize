"""One module's import changes, collected from every rule and applied once by `finish()`.

Emitted statements replace the legacy statement that caused them, in place, keeping its comments;
a fresh import is anchored only to one that runs. `offer()`/`require()` let one rule own a
submodule's names and any other ask by path, so the file gets one `from google.genai import types`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import libcst as cst
from libcst.metadata import MetadataWrapper, ParentNodeProvider, ScopeProvider

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
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


@dataclass(slots=True)
class _Anchor:
    """One legacy statement, and the statements that take its place."""

    # Held so the node stays alive: the plan is keyed by `id()`.
    statement: cst.SimpleStatementLine
    nodes: list[cst.BaseSmallStatement] = field(default_factory=list)


class ImportPlan:
    """The import changes one file's rules have asked for, not yet applied."""

    def __init__(self, wrapper: MetadataWrapper) -> None:
        self._bound = set(bound_names(wrapper))
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


def dotted_name(node: cst.BaseExpression) -> str:
    """The dotted path an import statement's `Attribute`/`Name` chain spells."""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return f"{dotted_name(node.value)}.{node.attr.value}"
    return ""  # pragma: no cover - an import target is always a dotted name


def _bare(node: cst.BaseSmallStatement) -> cst.BaseSmallStatement:
    """One statement per line, so a semicolon carried over from the source goes."""
    return node.with_changes(semicolon=cst.MaybeSentinel.DEFAULT)
