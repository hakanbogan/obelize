"""Read one release's public API with griffe, and print it as JSON. Run as a child process
(`python -P -m obelize.apidiff <root> <module>`, the module's `__main__`).

griffe parses source with the interpreter's `ast`, so a stranger's file can exhaust the stack or
the memory; here it can only end this process, whose limits the parent sets and whose output the
parent reads as data. Nothing in the library is imported or executed (`allow_inspection=False`).
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import griffe

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

# What one surface may hold, and how deep a class may nest.
MAX_OBJECTS: Final = 200_000
MAX_DEPTH: Final = 8
VALUE_CHARS: Final = 80
_DEPRECATED_CATEGORIES: Final = ("Deprecat", "FutureWarning")
_DYNAMIC: Final = frozenset({"__getattr__", "__dir__"})


def main(argv: list[str]) -> int:
    root, module = Path(argv[0]), argv[1]
    try:
        document = surface(root, module)
    except Exception as error:
        print(json.dumps({"error": f"{type(error).__name__}: {error}"[:500]}))
        return 3
    sys.stdout.write(json.dumps(document, separators=(",", ":")))
    return 0


def surface(root: Path, module: str) -> dict[str, Any]:
    loaded = griffe.load(
        module,
        search_paths=[root],
        allow_inspection=False,
        try_relative_path=False,
        store_source=False,
    )
    if not isinstance(loaded, griffe.Module):
        raise TypeError(f"{module} is not a module")
    walker = _Walker(module.split(".")[0])
    walker.visit(loaded, 0)
    return {"module": module, "objects": walker.objects, "truncated": walker.truncated}


class _Facts(NamedTuple):
    """What one file says that griffe does not: each deprecation warning's line and message, the
    messages of those run on import, the lines of the functions that are stubs, and the names a
    module-level `__getattr__` makes (`None`: it makes names it does not list)."""

    calls: list[tuple[int, str]]
    at_import: list[str]
    trivial: set[int]
    made: dict[str, str | None] | None


class _Walker:
    def __init__(self, package: str) -> None:
        self.package = package
        self.objects: dict[str, dict[str, Any]] = {}
        self.truncated = False
        self.files: dict[Path, _Facts] = {}

    def visit(self, module: Any, depth: int) -> None:
        exported = {str(one) for one in module.exports or ()}
        made = self._made(module)
        self.objects[module.path] = {
            "kind": "module",
            "deprecated": self._module_notice(module),
            # A `__getattr__` that lists no names makes any, so a name not seen may be there.
            "lazy": "__getattr__" in module.members and made is None,
        }
        # Names a module declares or makes, which no statement defines: known, not read.
        for name in sorted({*exported, *(made or ())} - set(module.members)):
            self.objects[f"{module.path}.{name}"] = {
                "kind": "name",
                "deprecated": (made or {}).get(name),
            }
        for name, member in list(module.members.items()):
            if self._full():
                return
            if name in _DYNAMIC or (_private(name) and name not in exported):
                continue
            if member.is_alias:
                self._alias(module, name, member, exported)
            elif member.is_module:
                if depth < MAX_DEPTH:
                    self.visit(member, depth + 1)
            elif member.is_class:
                self._class(member, depth)
            elif member.is_function:
                self.objects[member.path] = self._function(member, in_class=False)
            elif name != "__all__":
                self.objects[member.path] = self._attribute(member)

    def _full(self) -> bool:
        self.truncated = self.truncated or len(self.objects) >= MAX_OBJECTS
        return self.truncated

    def _public(self, dotted: str, name: str, exported: set[str]) -> bool:
        return dotted.split(".")[0] == self.package or name in exported

    def _alias(self, parent: Any, name: str, member: Any, exported: set[str]) -> None:
        """A name re-exported from elsewhere is a public name; its target is the object."""
        path = f"{parent.path}.{name}"
        try:
            target = member.final_target
        except (griffe.AliasResolutionError, griffe.CyclicAliasError):
            # An import griffe cannot follow is a name only if the package or `__all__` says so.
            if self._public(str(member.target_path), name, exported):
                self.objects[path] = {"kind": "alias", "target": str(member.target_path)}
            return
        # A target griffe could follow is in this package: it loaded nothing else.
        if target.is_function:
            record = self._function(target, in_class=False)
        elif target.is_class:
            record = self._class_record(target)
        elif target.is_attribute:
            record = self._attribute(target)
        else:
            return
        self.objects[path] = {**record, "target": target.path}

    def _class(self, member: Any, depth: int) -> None:
        self.objects[member.path] = self._class_record(member)
        if depth >= MAX_DEPTH:
            return
        for name, inner in list(member.members.items()):
            if self._full():
                return
            # The signature of `__init__` is the class's own.
            if inner.is_alias or _private(name) or name == "__init__":
                continue
            if inner.is_function:
                self.objects[inner.path] = self._function(inner, in_class=True)
            elif inner.is_class:
                self._class(inner, depth + 1)
            else:
                self.objects[inner.path] = self._attribute(inner)

    def _class_record(self, member: Any) -> dict[str, Any]:
        init = member.members.get("__init__")
        has_init = init is not None and init.is_function
        decorated = _decorated(member)
        return {
            "kind": "class",
            "bases": [str(base) for base in member.bases],
            "inherited": _inherited(member),
            # A class with no `__init__` of its own has no signature to compare.
            "params": _params(init, in_class=True) if has_init else None,
            "deprecated": decorated
            if decorated is not None
            else (self._notice(init) if has_init else None),
        }

    def _function(self, member: Any, *, in_class: bool) -> dict[str, Any]:
        static = any(str(one.value) == "staticmethod" for one in member.decorators)
        decorated = _decorated(member)
        return {
            "kind": "function",
            "params": _params(member, in_class=in_class and not static),
            "returns": _text(member.returns),
            "trivial": self._trivial(member),
            "deprecated": decorated if decorated is not None else self._notice(member),
        }

    def _attribute(self, member: Any) -> dict[str, Any]:
        """griffe reads a property as an attribute, whose getter may warn."""
        if "property" in member.labels:
            return {"kind": "attribute", "value": "property", "deprecated": self._notice(member)}
        return {"kind": "attribute", "value": _text(member.value), "deprecated": None}

    def _facts(self, path: Path) -> _Facts:
        if path not in self.files:
            self.files[path] = _file_facts(path)
        return self.files[path]

    def _notice(self, member: Any) -> str | None:
        located = _located(member)
        if located is None:  # pragma: no cover - griffe gives what it parsed a file and lines
            return None
        path, first, last = located
        inside = [text for line, text in self._facts(path).calls if first <= line <= last]
        return inside[0] if inside else None

    def _trivial(self, member: Any) -> bool:
        located = _located(member)
        return located is not None and located[1] in self._facts(located[0]).trivial

    def _made(self, module: Any) -> dict[str, str | None] | None:
        """The names the module's `__getattr__` makes; nothing, for a module without one."""
        path = module.filepath
        if "__getattr__" not in module.members or not isinstance(path, Path):
            return {}
        return self._facts(path).made

    def _module_notice(self, module: Any) -> str | None:
        # A namespace package has no file of its own.
        path = module.filepath
        at_import = self._facts(path).at_import if isinstance(path, Path) else []
        return at_import[0] if at_import else None


def _located(member: Any) -> tuple[Path, int, int] | None:
    path, first, last = member.filepath, member.lineno, member.endlineno
    return (path, first, last) if isinstance(path, Path) and first and last else None


def _inherited(member: Any) -> list[str]:
    """The public names a class gets from the classes it derives from, as far as they resolve."""
    return sorted(name for name in member.inherited_members if not _private(name))


def _private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _text(expression: Any) -> str | None:
    return None if expression is None else str(expression)[:VALUE_CHARS]


def _params(member: Any, *, in_class: bool) -> list[dict[str, Any]]:
    rows = []
    for index, parameter in enumerate(member.parameters):
        if in_class and index == 0 and parameter.name in ("self", "cls"):
            continue
        rows.append(
            {
                "name": parameter.name,
                "kind": parameter.kind.value,
                "default": _text(parameter.default),
                "required": parameter.required,
            }
        )
    return rows


def _decorated(member: Any) -> str | None:
    """The message of a `@deprecated("...")` decorator, or `""` for one with none."""
    for decorator in member.decorators:
        call = ast.parse(str(decorator.value), mode="eval").body
        if isinstance(call, ast.Call) and _called(call) == "deprecated":
            return _message(call.args[0]) if call.args else ""
    return None


def _file_facts(path: Path) -> _Facts:
    tree = ast.parse(path.read_bytes())
    calls = []
    trivial = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (text := _warning(node)) is not None:
            calls.append((node.lineno, text))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _empty(node.body):
            trivial.add(node.lineno)
    return _Facts(calls, list(_at_import(tree.body)), trivial, _made(tree))


def _made(tree: ast.Module) -> dict[str, str | None] | None:
    """The names a module-level `__getattr__` makes, each with the deprecation message of the branch
    that makes it, or `None` if it uses the name it is asked for in any way but to compare it with
    names it lists (or to look it up in a table of them) and to say it has none."""
    function = next(
        (
            one
            for one in tree.body
            if isinstance(one, ast.FunctionDef) and one.name == "__getattr__"
        ),
        None,
    )
    if function is None or not function.args.args:
        return None
    asked = function.args.args[0].arg
    tables = _tables(tree)
    made: dict[str, str | None] = {}
    understood: set[int] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.If) and (listed := _listed(node.test, asked, tables)) is not None:
            said = next(
                (
                    text
                    for one in ast.walk(node)
                    if isinstance(one, ast.Call) and (text := _warning(one))
                ),
                None,
            )
            made.update(dict.fromkeys(listed[0], said))
            understood.update(listed[1])
        elif isinstance(node, ast.Subscript | ast.Call) and (
            looked := _looked_up(node, asked, tables)
        ):
            made.update(dict.fromkeys(looked[0]))
            understood.update(looked[1])
        elif isinstance(node, ast.Raise):
            understood.update(id(one) for one in ast.walk(node) if _is(one, asked))
    uses = [one for one in ast.walk(function) if _is(one, asked)]
    return made if all(id(one) in understood for one in uses) else None


def _is(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _strings(nodes: Sequence[ast.expr | None]) -> list[str] | None:
    """The strings of a list of constants, or `None` if any is something else."""
    found = [
        one.value for one in nodes if isinstance(one, ast.Constant) and isinstance(one.value, str)
    ]
    return found if len(found) == len(nodes) else None


def _tables(tree: ast.Module) -> dict[str, list[str]]:
    """Module-level names bound to a dict, set, list or tuple of strings, with those strings."""
    found: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        keys = value.keys if isinstance(value, ast.Dict) else getattr(value, "elts", None)
        strings = None if keys is None else _strings(keys)
        if isinstance(target, ast.Name) and strings is not None:
            found[target.id] = strings
    return found


def _listed(
    test: ast.expr, asked: str, tables: dict[str, list[str]]
) -> tuple[list[str], list[int]] | None:
    """The names `asked == "x"` or `asked in (...)` lists, and the uses of `asked` it covers."""
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and _is(test.left, asked)):
        return None
    right, op = test.comparators[0], test.ops[0]
    if isinstance(op, ast.Eq):
        listed = _strings([right])
    elif isinstance(op, ast.In):
        table = tables.get(right.id) if isinstance(right, ast.Name) else None
        listed = table if table is not None else _strings(getattr(right, "elts", [None]))
    else:
        listed = None
    return None if listed is None else (listed, [id(test.left)])


def _looked_up(
    node: ast.AST, asked: str, tables: dict[str, list[str]]
) -> tuple[list[str], list[int]] | None:
    """The names of a table that `table[asked]` or `table.get(asked)` reads."""
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and _is(node.slice, asked)
    ):
        table, use = node.value.id, node.slice
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and len(node.args) == 1
        and _is(node.args[0], asked)
    ):
        table, use = node.func.value.id, node.args[0]
    else:
        return None
    return (tables[table], [id(use)]) if table in tables else None


def _empty(body: list[ast.stmt]) -> bool:
    """A body of a docstring, `pass` and `...` only: a stub, which says nothing of the function."""
    return all(
        isinstance(one, ast.Pass)
        or (isinstance(one, ast.Expr) and isinstance(one.value, ast.Constant))
        for one in body
    )


def _at_import(body: list[ast.stmt]) -> Iterator[str]:
    """Warnings reached when the module is imported: not inside a function or a class."""
    for statement in body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            text = _warning(statement.value)
            if text is not None:
                yield text
        inner: list[ast.stmt] = []
        for field in ("body", "orelse", "finalbody"):
            inner += getattr(statement, field, [])
        for handler in getattr(statement, "handlers", []):
            inner += handler.body
        yield from _at_import(inner)


def _called(node: ast.Call) -> str:
    return node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")


def _warning(node: ast.Call) -> str | None:
    """The message of `warnings.warn(message, DeprecationWarning-like)`, or `None`."""
    if _called(node) != "warn" or not node.args:
        return None
    category = (
        node.args[1]
        if len(node.args) > 1
        else next((one.value for one in node.keywords if one.arg == "category"), None)
    )
    label = category.attr if isinstance(category, ast.Attribute) else getattr(category, "id", "")
    if not any(part in label for part in _DEPRECATED_CATEGORIES):
        return None
    return _message(node.args[0])


def _message(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return " ".join(node.value.split())
    if isinstance(node, ast.JoinedStr):
        parts = (
            str(part.value) if isinstance(part, ast.Constant) else "{}" for part in node.values
        )
        return " ".join("".join(parts).split())
    return ""
