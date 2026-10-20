"""The classes of a repository that derive from a library's, found before any file is analysed.

`class Admin(User)` in one file and `Admin().dict()` in another name the library in neither, and a
file that never names it is not parsed. So the repository's class headers are read first, cheaply
and once, and the files that define a class deriving from one a pack names are read properly, with
`ast`, which is far cheaper than the analysis. A class is then found by the name an import gives it
and the module that import comes from; a name the repository defines more than once, not always as
a derived class, is not one. What this reads is the module level of each file: a class defined in a
function, or by `type(...)`, is not found.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from obelize.scan.members import Lineage, combine

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

    from obelize.models import ScanSpec

# The header of a class, on bytes: its name and what is between the brackets, however many lines.
_HEAD = re.compile(
    rb"^[ \t]*class[ \t]+([A-Za-z_][A-Za-z0-9_]*)[ \t]*(?:\(([^)]{0,1000})\))?", re.MULTILINE
)
_AS = re.compile(rb"\b([A-Za-z_][A-Za-z0-9_]*)[ \t]+as[ \t]+([A-Za-z_][A-Za-z0-9_]*)")
_WORDS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

Heads = tuple[tuple[str, str], ...]


def heads(data: bytes) -> Heads:
    """Each class header in `data` as the name and the text of its bases."""
    return tuple(
        (one[1].decode(), (one[2] or b"").decode("utf-8", "replace"))
        for one in _HEAD.finditer(data)
    )


def aliases(data: bytes) -> frozenset[tuple[str, str]]:
    """Each `name as other` in `data`, as (other, name): what a class header may spell instead."""
    return frozenset((one[2].decode(), one[1].decode()) for one in _AS.finditer(data))


def module_of(path: str) -> str:
    """The dotted module a file is: `app/models.py` is `app.models`, `app/__init__.py` is `app`."""
    parts = path.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


@dataclass(frozen=True, slots=True)
class Derived:
    module: str
    name: str
    lineage: Lineage


class Index:
    """The derived classes of a repository, where every class of those names is defined, and what
    the classes that derive from nothing but sit beside one in a base list define."""

    def __init__(
        self,
        derived: Collection[Derived] = (),
        defined: Collection[tuple[str, str]] = (),
        shadows: Collection[tuple[str, str, frozenset[str]]] = (),
    ) -> None:
        self.derived = tuple(sorted(derived, key=lambda one: (one.name, one.module)))
        self.defined = tuple(sorted(defined))
        self.shadows = tuple(sorted(shadows, key=lambda one: (one[0], one[1], sorted(one[2]))))
        self._by_name: dict[str, list[Derived]] = {}
        for one in self.derived:
            self._by_name.setdefault(one.name, []).append(one)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._by_name)

    @property
    def overridden(self) -> frozenset[tuple[str, str]]:
        """Each (library class, member) that a class of the repository derived from it defines."""
        return frozenset(
            (one.lineage.base, name) for one in self.derived for name in one.lineage.overrides
        )

    def restricted(self, spec: ScanSpec) -> Index:
        """What `spec` reads: the classes that derive from one of its own."""
        bases = {entry.class_symbol for entry in spec.member_classes}
        kept = [one for one in self.derived if one.lineage.base in bases]
        return Index(kept, self.defined, self.shadows)

    def mentions(self, data: bytes) -> bool:
        """Whether `data` spells the name of a derived class, so that a file may use one."""
        return any(name.encode() in data for name in self._by_name)

    def lookup(self, qualified: str) -> Lineage | None:
        """The lineage of the class an import gives this name (`pkg.models.User`, `.models.User`).

        The module an import names is read as part of the dotted path of a defining file, since a
        package re-exports what its modules define. A name defined elsewhere in the repository by
        a class that derives from nothing is not told from them, and is none.
        """
        module, _, name = qualified.rpartition(".")
        found = [one for one in self._by_name.get(name, ()) if _within(module, one.module)]
        places = {one.module for one in found}
        rival = any(
            called == name and _within(module, place) and place not in places
            for called, place in self.defined
        )
        bases = {one.lineage.base for one in found}
        if not found or rival or len(bases) != 1:
            return None
        return Lineage(next(iter(bases)), frozenset().union(*(o.lineage.overrides for o in found)))

    def shadow(self, qualified: str) -> frozenset[str]:
        """What the classes of the repository that this import may name, and that derive from
        nothing a pack names, define."""
        module, _, name = qualified.rpartition(".")
        return frozenset().union(
            *(
                defined
                for called, place, defined in self.shadows
                if called == name and _within(module, place)
            )
        )


EMPTY = Index()


def _within(imported: str, module: str) -> bool:
    """Whether the dotted path an import names runs through `module` (the dots of a relative one
    only say where from)."""
    wanted = [part for part in imported.split(".") if part]
    have = module.split(".")
    return any(have[at : at + len(wanted)] == wanted for at in range(len(have) - len(wanted) + 1))


def leaves(members: Mapping[str, frozenset[str]]) -> frozenset[str]:
    """The names the library's classes are written as, by their last name."""
    return frozenset(symbol.rpartition(".")[2] for symbol in members)


def build(
    found: Mapping[str, Heads],
    contents: Callable[[str], bytes | None],
    members: Mapping[str, frozenset[str]],
    spelled: Collection[tuple[str, str]] = (),
) -> Index:
    """The index of the classes that derive from one of `members`' keys, from each file's headers.

    `contents` gives the bytes of the files that define a class a header says may derive from one,
    or that a header puts in a base list beside one (a mixin that can define a member first), and
    `spelled` the names that imports give others (`Shape as Base` is `("Base", "Shape")`).
    """
    names = _candidates(found, leaves(members), spelled)
    if not names:
        return EMPTY
    defined = {
        (name, module_of(path))
        for path, heads_of in found.items()
        for name, _ in heads_of
        if name in names
    }
    beside = {
        word
        for heads_of in found.values()
        for name, bases in heads_of
        if name in names
        for word in _WORDS.findall(bases)
    } - names
    classes: list[_Class] = []
    for path, heads_of in sorted(found.items()):
        wanted = any(name in names or name in beside for name, _ in heads_of)
        if wanted and (data := contents(path)) is not None:
            classes.extend(_classes(module_of(path), data))
    derived, shadows = _derive(classes, members, defined)
    return Index(derived, defined, shadows)


def _candidates(
    found: Mapping[str, Heads], leaves: frozenset[str], spelled: Collection[tuple[str, str]]
) -> frozenset[str]:
    """The names of the classes whose bases may lead to a library's class: by what the bases spell,
    which is no more than a first cut."""
    names: set[str] = set()
    words = set(leaves)
    while True:
        words |= {other for other, name in spelled if name in words}
        more = {
            name
            for heads_of in found.values()
            for name, bases in heads_of
            if name not in names and not words.isdisjoint(_WORDS.findall(bases))
        }
        if not more:
            return frozenset(names)
        names |= more
        words |= more


@dataclass(frozen=True, slots=True)
class _Class:
    module: str
    name: str
    # Each base as the import qualifies it, or bare where the module defines it.
    bases: tuple[str, ...]
    defined: frozenset[str]
    # Whether the module binds the name once, by this class: any other binding makes it unknown.
    only: bool


def _classes(module: str, data: bytes) -> list[_Class]:
    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    imports = _imports(tree)
    bound = Counter(_bound(tree.body))
    return [
        _Class(
            module,
            node.name,
            _bases(node, imports),
            frozenset(_bound(node.body)),
            bound[node.name] == 1,
        )
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    ]


def _imports(tree: ast.Module) -> dict[str, str]:
    """What each name an import binds is, as libcst qualifies it: `.models.User` is relative."""
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound[alias.asname or alias.name.partition(".")[0]] = (
                    alias.name if alias.asname else alias.name.partition(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            source = "." * node.level + (node.module or "")
            joint = "." if node.module else ""
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{source}{joint}{alias.name}"
    return bound


def _bases(node: ast.ClassDef, imports: Mapping[str, str]) -> tuple[str, ...]:
    found = []
    for base in node.bases:
        dotted = _dotted(base)
        if dotted:
            root, _, rest = dotted.partition(".")
            found.append(
                f"{imports[root]}.{rest}" if rest and root in imports else imports.get(root, dotted)
            )
    return tuple(found)


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and (value := _dotted(node.value)):
        return f"{value}.{node.attr}"
    return ""


def _bound(nodes: Iterable[ast.AST]) -> list[str]:
    """The names statements bind at their own level, by any statement and in any branch: never
    those inside a function, a lambda or a nested class, whose own name is bound."""
    names: list[str] = []
    for node in nodes:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(node.name)
            continue
        if isinstance(node, ast.Assign | ast.Delete):
            names.extend(one for target in node.targets for one in _stored(target))
        elif isinstance(
            node, ast.AnnAssign | ast.AugAssign | ast.NamedExpr | ast.For | ast.AsyncFor
        ):
            names.extend(_stored(node.target))
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            names.extend(_stored(node.optional_vars))
        elif isinstance(node, ast.ExceptHandler) and node.name is not None:
            names.append(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names.extend(alias.asname or alias.name.partition(".")[0] for alias in node.names)
        names.extend(
            _bound(
                child for child in ast.iter_child_nodes(node) if not isinstance(child, ast.Lambda)
            )
        )
    return names


def _stored(target: ast.expr) -> list[str]:
    """The names an assignment target binds: `a, (b, *c) = ...` binds three."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Tuple | ast.List):
        return [one for element in target.elts for one in _stored(element)]
    if isinstance(target, ast.Starred):
        return _stored(target.value)
    return []


def _derive(
    classes: list[_Class],
    members: Mapping[str, frozenset[str]],
    defined: Collection[tuple[str, str]],
) -> tuple[list[Derived], list[tuple[str, str, frozenset[str]]]]:
    """The lineage of each class, to a fixed point (a class can derive from one found later), and
    what the classes with none define."""
    local: dict[tuple[str, str], list[_Class]] = {}
    for one in classes:
        local.setdefault((one.module, one.name), []).append(one)
    found: dict[tuple[str, str], Lineage] = {}
    grown, rounds = True, 0
    while grown and rounds <= len(classes):
        index = Index(
            [Derived(module, name, one) for (module, name), one in found.items()], defined
        )
        grown = False
        for one in classes:
            lineage = _lineage(one, local, found, members, index, classes)
            if one.only and lineage is not None and found.get((one.module, one.name)) != lineage:
                found[(one.module, one.name)] = lineage
                grown = True
        rounds += 1
    derived = [Derived(module, name, one) for (module, name), one in found.items()]
    shadows = [
        (one.name, one.module, one.defined)
        for one in classes
        if (one.module, one.name) not in found
    ]
    return derived, shadows


def _lineage(
    one: _Class,
    local: Mapping[tuple[str, str], list[_Class]],
    found: Mapping[tuple[str, str], Lineage],
    members: Mapping[str, frozenset[str]],
    index: Index,
    classes: Sequence[_Class],
) -> Lineage | None:
    lineages: set[Lineage] = set()
    shadowed: set[str] = set()
    for base in one.bases:
        beside = local.get((one.module, base), [])
        lineage: Lineage | None
        if base in members:
            lineage = Lineage(base, frozenset())
        elif beside:
            lineage = found.get((one.module, base))
        else:
            lineage = index.lookup(base)
        if lineage is not None:
            lineages.add(lineage)
        elif beside:
            shadowed.update(*(other.defined for other in beside))
        else:
            module, _, name = base.rpartition(".")
            shadowed.update(
                *(
                    other.defined
                    for other in classes
                    if other.name == name and _within(module, other.module)
                )
            )
    return combine(lineages, set(one.defined), shadowed, members)
