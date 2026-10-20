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
from dataclasses import dataclass
from typing import TYPE_CHECKING

from obelize.scan.members import Lineage, combine

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping

    from obelize.models import ScanSpec

# The header of a class, on bytes: its name and what is between the brackets, however many lines.
_HEAD = re.compile(
    rb"^[ \t]*class[ \t]+([A-Za-z_][A-Za-z0-9_]*)[ \t]*(?:\(([^)]*)\))?", re.MULTILINE
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
    """The derived classes of a repository, and where every class of those names is defined."""

    def __init__(
        self, derived: Collection[Derived] = (), defined: Collection[tuple[str, str]] = ()
    ) -> None:
        self.derived = tuple(sorted(derived, key=lambda one: (one.name, one.module)))
        self.defined = tuple(sorted(defined))
        self._by_name: dict[str, list[Derived]] = {}
        for one in self.derived:
            self._by_name.setdefault(one.name, []).append(one)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._by_name)

    def restricted(self, spec: ScanSpec) -> Index:
        """What `spec` reads: the classes that derive from one of its own."""
        bases = {entry.class_symbol for entry in spec.member_classes}
        return Index([one for one in self.derived if one.lineage.base in bases], self.defined)

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
    and `spelled` the names that imports give others (`Shape as Base` is `("Base", "Shape")`).
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
    classes: list[_Class] = []
    for path, heads_of in sorted(found.items()):
        if any(name in names for name, _ in heads_of) and (data := contents(path)) is not None:
            classes.extend(_classes(module_of(path), data))
    return Index(_derive(classes, members, defined), defined)


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


def _classes(module: str, data: bytes) -> list[_Class]:
    try:
        tree = ast.parse(data)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    imports = _imports(tree)
    return [
        _Class(module, node.name, _bases(node, imports), _defined(node))
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


def _defined(node: ast.ClassDef) -> frozenset[str]:
    names: set[str] = set()
    for statement in node.body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(statement.name)
        elif isinstance(statement, ast.Assign):
            names.update(one.id for one in statement.targets if isinstance(one, ast.Name))
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            names.add(statement.target.id)
    return frozenset(names)


def _derive(
    classes: list[_Class],
    members: Mapping[str, frozenset[str]],
    defined: Collection[tuple[str, str]],
) -> list[Derived]:
    """The lineage of each class, to a fixed point: a class can derive from one found later."""
    local = {(one.module, one.name): one for one in classes}
    found: dict[tuple[str, str], Lineage] = {}
    grown, rounds = True, 0
    while grown and rounds <= len(classes):
        index = Index(
            [Derived(module, name, one) for (module, name), one in found.items()], defined
        )
        grown = False
        for one in classes:
            lineage = _lineage(one, local, found, members, index)
            if lineage is not None and found.get((one.module, one.name)) != lineage:
                found[(one.module, one.name)] = lineage
                grown = True
        rounds += 1
    return [Derived(module, name, one) for (module, name), one in found.items()]


def _lineage(
    one: _Class,
    local: Mapping[tuple[str, str], _Class],
    found: Mapping[tuple[str, str], Lineage],
    members: Mapping[str, frozenset[str]],
    index: Index,
) -> Lineage | None:
    lineages: set[Lineage] = set()
    shadowed: set[str] = set()
    for base in one.bases:
        beside = local.get((one.module, base))
        lineage: Lineage | None
        if base in members:
            lineage = Lineage(base, frozenset())
        elif beside is not None:
            lineage = found.get((one.module, base))
        else:
            lineage = index.lookup(base)
        if lineage is not None:
            lineages.add(lineage)
        elif beside is not None:
            shadowed |= beside.defined
    return combine(lineages, set(one.defined), shadowed, members)
