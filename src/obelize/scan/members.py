"""Where a member a pack renames is read off an instance of its class (`rename_member`).

The class is the library's; the instance is a repository's, usually: `class User(BaseModel)` and
`user.dict()` name the library once, in the first. So the receiver is typed from what is known of
it (a call of a class, a name every assignment of which is one, `self` in a method, a parameter
annotated with one) and a receiver nothing types is left as it is, not guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import libcst as cst
from libcst.metadata import Assignment, GlobalScope, QualifiedNameSource

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence

    from libcst.metadata import BaseAssignment, QualifiedName, Scope

    from obelize.models import ConfidenceReason, ScanSpec

# Deeper than any chain of names assigned from one another that a person writes.
_DEPTH: Final = 8

_BY_CLASS: Final[ConfidenceReason] = "receiver_typed_by_class"
_SAME_SCOPE: Final[ConfidenceReason] = "receiver_bound_same_scope"
_MODULE_CONST: Final[ConfidenceReason] = "receiver_bound_module_const"


@dataclass(frozen=True, slots=True)
class Lineage:
    """A class that derives from one a pack names: that class, and the renamed members the classes
    between define, since a member one of them defines is no longer the library's."""

    base: str
    overrides: frozenset[str]


@dataclass(frozen=True, slots=True)
class Typed:
    lineage: Lineage
    reason: ConfidenceReason


@dataclass(frozen=True, slots=True)
class Hit:
    """A member read off a typed receiver; `node` is the member's name in the source."""

    node: cst.Name
    called: bool
    symbol: str
    reason: ConfidenceReason
    overridden: bool


def _nothing(name: str) -> Lineage | None:
    return None


@dataclass(frozen=True, slots=True)
class Source:
    """What one file gives the reader: its nodes, and the metadata libcst resolved over them."""

    classes: Sequence[cst.ClassDef]
    attributes: Sequence[cst.Attribute]
    annotated: Sequence[cst.AnnAssign]
    # An assignment's target to the value it takes.
    values: Mapping[int, cst.BaseExpression]
    scopes: Mapping[cst.CSTNode, Scope | None]
    parents: Mapping[cst.CSTNode, cst.CSTNode]
    qualified: Callable[[cst.CSTNode], set[QualifiedName]]
    # What another module of the repository defines: a class by the name an import gives it.
    derived: Callable[[str], Lineage | None] = _nothing


def read(spec: ScanSpec, source: Source) -> list[Hit]:
    """Every member of `spec.member_classes` read off a receiver the file types."""
    return _Reader(spec, source).hits()


class _Reader:
    def __init__(self, spec: ScanSpec, source: Source) -> None:
        self._source = source
        self._members = {
            entry.class_symbol: frozenset(entry.members) for entry in spec.member_classes
        }
        self._wanted = frozenset().union(*self._members.values())
        self._annotations = {
            id(node.target): node.annotation.annotation for node in source.annotated
        }
        counted: dict[str, list[cst.ClassDef]] = {}
        for class_def in source.classes:
            counted.setdefault(class_def.name.value, []).append(class_def)
        # A class is found by its name only where the file defines one such class.
        self._here = {name: found[0] for name, found in counted.items() if len(found) == 1}
        self._lineages: dict[int, Lineage | None] = {}

    def hits(self) -> list[Hit]:
        found = []
        for attribute in self._source.attributes:
            member = attribute.attr.value
            if member not in self._wanted:
                continue
            typed = self._typed(attribute.value, _DEPTH)
            if typed is None or member not in self._members[typed.lineage.base]:
                continue
            parent = self._source.parents.get(attribute)
            found.append(
                Hit(
                    node=attribute.attr,
                    called=isinstance(parent, cst.Call) and parent.func is attribute,
                    symbol=f"{typed.lineage.base}.{member}",
                    reason=typed.reason,
                    overridden=member in typed.lineage.overrides,
                )
            )
        return found

    def _typed(self, node: cst.BaseExpression, depth: int) -> Typed | None:
        """The class an expression is an instance of, or the class itself, where it can be told."""
        if isinstance(node, cst.Call):
            return self._by_class(self._class(node.func))
        if isinstance(node, cst.Attribute):
            return self._by_class(self._class(node))
        if isinstance(node, cst.Name) and depth > 0:
            return self._by_class(self._class(node)) or self._name(node, depth)
        return None

    @staticmethod
    def _by_class(lineage: Lineage | None) -> Typed | None:
        return None if lineage is None else Typed(lineage, _BY_CLASS)

    def _name(self, node: cst.Name, depth: int) -> Typed | None:
        """A name is typed when every assignment of it says the same class."""
        scope = self._source.scopes.get(node)
        found = {self._assigned(item, scope, depth) for item in _assignments(scope, node.value)}
        return next(iter(found)) if len(found) == 1 else None

    def _assigned(self, item: object, access: Scope | None, depth: int) -> Typed | None:
        if not isinstance(item, Assignment):
            return None
        target = item.node
        if isinstance(target, cst.Param):
            return self._param(target)
        if not isinstance(target, cst.Name):
            return None
        annotation = self._annotations.get(id(target))
        if annotation is not None:
            return self._by_class(self._annotated(annotation))
        value = self._source.values.get(id(target))
        typed = None if value is None else self._typed(value, depth - 1)
        if typed is None:
            return None
        # A name bound at module level and read in a function is read through the module.
        through = isinstance(item.scope, GlobalScope) and item.scope is not access
        return Typed(typed.lineage, _MODULE_CONST if through else _SAME_SCOPE)

    def _param(self, param: cst.Param) -> Typed | None:
        """A parameter is what it is annotated as; `self` and `cls` are the class they are in."""
        if param.annotation is not None:
            return self._by_class(self._annotated(param.annotation.annotation))
        parameters = self._source.parents.get(param)
        function = self._source.parents.get(parameters) if parameters is not None else None
        if not isinstance(function, cst.FunctionDef) or function.params.params[:1] != (param,):
            return None
        if any(_leaf(decorator.decorator) == "staticmethod" for decorator in function.decorators):
            return None
        block = self._source.parents.get(function)
        owner = self._source.parents.get(block) if block is not None else None
        return self._by_class(self._lineage(owner)) if isinstance(owner, cst.ClassDef) else None

    def _annotated(self, annotation: cst.BaseExpression) -> Lineage | None:
        """The class an annotation names; an `Optional` or `| None` of one is that class."""
        annotation = _without_none(annotation)
        if isinstance(annotation, cst.SimpleString):
            text = annotation.evaluated_value
            found = self._here.get(text) if isinstance(text, str) else None
            return None if found is None else self._lineage(found)
        return self._class(annotation)

    def _class(self, node: cst.BaseExpression) -> Lineage | None:
        """The class a name or an attribute is, where the repository derives it from a library's."""
        imported = {
            name.name
            for name in self._source.qualified(node)
            if name.source is QualifiedNameSource.IMPORT
        }
        if imported:
            lineages = {self._source.derived(name) for name in imported}
            return next(iter(lineages)) if len(lineages) == 1 else None
        defined = self._defined_by(node)
        lineages = {self._lineage(class_def) for class_def in defined}
        return next(iter(lineages)) if defined and len(lineages) == 1 else None

    def _defined_by(self, node: cst.CSTNode) -> list[cst.ClassDef]:
        """The classes of this file that every assignment of a name is, or none."""
        name = node.value if isinstance(node, cst.Name) else ""
        found = [
            item.node if isinstance(item, Assignment) else None
            for item in _assignments(self._source.scopes.get(node), name)
        ]
        classes = [one for one in found if isinstance(one, cst.ClassDef)]
        return classes if len(classes) == len(found) else []

    def _lineage(self, class_def: cst.ClassDef) -> Lineage | None:
        """What a class derives from that a pack names, and what the classes between it define.

        A class that derives from two such libraries' classes is neither, and one that derives from
        itself has no lineage.
        """
        key = id(class_def)
        if key in self._lineages:
            return self._lineages[key]
        self._lineages[key] = None
        found: set[Lineage] = set()
        shadowed: set[str] = set()
        for argument in class_def.bases:
            if argument.keyword is not None or argument.star:
                continue
            lineage = self._base(argument.value)
            if lineage is not None:
                found.add(lineage)
                continue
            # A class of this file that is no library's can still define the member first.
            shadowed |= {
                one for mixin in self._defined_by(argument.value) for one in _defined(mixin)
            }
        self._lineages[key] = combine(found, _defined(class_def), shadowed, self._members)
        return self._lineages[key]

    def _base(self, node: cst.BaseExpression) -> Lineage | None:
        """A base that is a library's class a pack names, or a class derived from one."""
        for name in self._source.qualified(node):
            if name.source is QualifiedNameSource.IMPORT and name.name in self._members:
                return Lineage(name.name, frozenset())
        return self._class(node)


def combine(
    found: Collection[Lineage],
    own: set[str],
    shadowed: set[str],
    members: Mapping[str, frozenset[str]],
) -> Lineage | None:
    """The lineage a class has from those of its bases and the names it, and the classes beside
    them in its base list, define; bases from two libraries' classes leave it none."""
    bases = {one.base for one in found}
    if len(bases) != 1:
        return None
    base = next(iter(bases))
    carried = frozenset().union(*(one.overrides for one in found))
    return Lineage(base, carried | ((own | shadowed) & members[base]))


def _assignments(scope: Scope | None, name: str) -> Collection[BaseAssignment]:
    """What a scope says a name is assigned from, or nothing where the node has no scope."""
    return () if scope is None or not name else scope[name]


def _defined(class_def: cst.ClassDef) -> set[str]:
    """The names a class body defines itself: a method, an assignment or an annotated field."""
    names: set[str] = set()
    for statement in class_def.body.body:
        if isinstance(statement, cst.FunctionDef):
            names.add(statement.name.value)
        elif isinstance(statement, cst.SimpleStatementLine):
            for small in statement.body:
                targets = (
                    [target.target for target in small.targets]
                    if isinstance(small, cst.Assign)
                    else [small.target]
                    if isinstance(small, cst.AnnAssign)
                    else []
                )
                names.update(one.value for one in targets if isinstance(one, cst.Name))
    return names


def _leaf(node: cst.BaseExpression) -> str:
    """The last name of a name or an attribute: `typing.Optional` is `Optional`."""
    if isinstance(node, cst.Name):
        return node.value
    return node.attr.value if isinstance(node, cst.Attribute) else ""


def _without_none(annotation: cst.BaseExpression) -> cst.BaseExpression:
    """`Optional[X]` and `X | None` as `X`; any other annotation as it is."""
    if (
        isinstance(annotation, cst.Subscript)
        and _leaf(annotation.value) == "Optional"
        and len(annotation.slice) == 1
        and isinstance(annotation.slice[0].slice, cst.Index)
    ):
        return annotation.slice[0].slice.value
    if isinstance(annotation, cst.BinaryOperation) and isinstance(annotation.operator, cst.BitOr):
        if _leaf(annotation.right) == "None":
            return annotation.left
        if _leaf(annotation.left) == "None":
            return annotation.right
    return annotation
