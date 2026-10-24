"""The templates of `rewrite_pattern`: a Python expression where `$name` stands for any expression.

A template is data, never run and never a regular expression. It is parsed once, by libcst; a call
is compared with it by form (not by spacing, parentheses or the order of the keywords), and the
second template is built over the expressions the first bound. Only the forms below can be written,
so what a pattern matches is what a person reading it sees.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

import libcst as cst

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

# Longer than any pattern a person writes, and short enough that no pack carries a program.
LIMIT: Final = 2000
# Levels a template may nest in `ast`'s tree: a person's has under ten, and libcst's native parser
# overruns the stack of a Windows process on a deeper one, which kills the run where `ast` raises.
DEPTH: Final = 40
_DEEP: Final = "is nested too deeply to read"
_META: Final = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_PREFIX: Final = "obelize_meta_"

# The expressions a template may hold; anything else is refused when the pack loads.
_FORMS: Final = (
    cst.Name,
    cst.Attribute,
    cst.Call,
    cst.Integer,
    cst.Float,
    cst.SimpleString,
    cst.Tuple,
    cst.List,
    cst.Dict,
    cst.Subscript,
    cst.UnaryOperation,
)


# The builtins a template may write without a root: functions that only build a value from their
# arguments. `open`, `eval`, `exec`, `__import__`, `getattr` and the rest that reach out are not
# here.
PURE: Final = frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "bytes",
        "dict",
        "enumerate",
        "float",
        "frozenset",
        "int",
        "filter",
        "isinstance",
        "len",
        "list",
        "map",
        "max",
        "min",
        "range",
        "reversed",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    }
)


# The names Python reserves for its three constants, which are no module to import.
CONSTANTS: Final = frozenset({"None", "True", "False"})


class TemplateError(ValueError):
    """A template that cannot be read, in words for a pack's author."""


@dataclass(frozen=True, slots=True)
class Template:
    tree: cst.BaseExpression
    # The metavariables it holds, and how many times each is written.
    names: frozenset[str]
    uses: Mapping[str, int]
    # The names it spells out as dotted chains, the attributes it reads, and whether it has a
    # string.
    spelled: frozenset[str]
    attributes: frozenset[str]
    strings: bool


def parse(text: str) -> Template:
    """The template `text` is; raises `TemplateError` for one that is too long, does not parse, or
    holds a form a template cannot."""
    if len(text) > LIMIT:
        raise TemplateError(f"is {len(text)} characters long, over the {LIMIT} a template may be")
    if _PREFIX in text:
        raise TemplateError(f"holds {_PREFIX!r}, which a template reserves for its own names")
    source = _META.sub(lambda found: _PREFIX + found[1], text)
    _looked_at(source)
    try:
        tree = cst.parse_expression(source)
        found = _Forms()
        tree.visit(found)
        spelled: set[str] = set()
        _spelled(tree, spelled)
    except cst.ParserSyntaxError as error:
        raise TemplateError(f"does not parse: {error.message}") from error
    return Template(
        tree,
        frozenset(found.uses),
        dict(found.uses),
        frozenset(spelled),
        frozenset(found.attributes),
        found.strings,
    )


def _looked_at(source: str) -> None:
    """Raise `TemplateError` for a template Python refuses or finds nested past `DEPTH`.

    Asked before libcst, which `ast` answers with an exception where libcst's parser overruns the
    stack; walked without recursion, since the input is what overruns it.
    """
    try:
        stack: list[tuple[ast.AST, int]] = [(ast.parse(source.strip(), mode="eval"), 0)]
        while stack:
            node, depth = stack.pop()
            if depth > DEPTH:
                raise TemplateError(_DEEP)
            stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    except SyntaxError as error:
        raise TemplateError(f"does not parse: {error.msg}") from error
    except (RecursionError, MemoryError) as error:
        raise TemplateError(_DEEP) from error


def _meta(node: cst.CSTNode) -> str | None:
    """The metavariable a name is, or `None`."""
    if isinstance(node, cst.Name) and node.value.startswith(_PREFIX):
        return node.value[len(_PREFIX) :]
    return None


class _Forms(cst.CSTVisitor):
    def __init__(self) -> None:
        self.uses: Counter[str] = Counter()
        self.attributes: set[str] = set()
        self.strings = False

    def on_visit(self, node: cst.CSTNode) -> bool:
        if isinstance(node, cst.BaseExpression) and not isinstance(node, _FORMS):
            raise TemplateError(f"holds a {type(node).__name__}, which a template cannot")
        return super().on_visit(node)

    def visit_Name(self, node: cst.Name) -> None:
        if (name := _meta(node)) is not None:
            self.uses[name] += 1
        elif node.value.startswith("__") and node.value.endswith("__"):
            raise TemplateError(f"holds {node.value}, a name that reaches the interpreter")

    def visit_Attribute(self, node: cst.Attribute) -> None:
        if _meta(node.attr) is not None:
            raise TemplateError(
                "names an attribute with a metavariable, which stands for an expression"
            )
        self.attributes.add(node.attr.value)

    def visit_SimpleString(self, node: cst.SimpleString) -> None:
        if _PREFIX in node.value:
            raise TemplateError("holds a $name inside a string, where it stands for no expression")
        self.strings = True

    def visit_Subscript(self, node: cst.Subscript) -> None:
        if len(node.slice) != 1 or not isinstance(node.slice[0].slice, cst.Index):
            raise TemplateError("holds a subscript that is not one index, which a template cannot")
        if node.slice[0].slice.star is not None:
            raise TemplateError("holds a starred index, which a template cannot")

    def visit_Call(self, node: cst.Call) -> None:
        keywords = [argument.keyword.value for argument in node.args if argument.keyword]
        if len(set(keywords)) != len(keywords):
            raise TemplateError("names a keyword twice, which no call can")

    def visit_Arg(self, node: cst.Arg) -> None:
        if node.star:
            raise TemplateError("holds a `*` or `**` argument, which a template cannot")
        if node.keyword is not None and _meta(node.keyword) is not None:
            raise TemplateError(
                "names a keyword with a metavariable, which stands for an expression"
            )

    def visit_StarredDictElement(self, node: cst.StarredDictElement) -> None:
        raise TemplateError("holds a `**` entry, which a template cannot")


def dotted(node: cst.CSTNode) -> str:
    """The dotted name of a chain of names and attributes, or `""` for anything else."""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute) and (head := dotted(node.value)):
        return f"{head}.{node.attr.value}"
    return ""


@dataclass(frozen=True, slots=True)
class Anchor:
    """What a pattern is found by: the qualified name its call is of."""

    symbol: str
    # The metavariable the call is made on, when the call is a member of a typed receiver.
    receiver: str | None


def anchor(before: Template, where: Mapping[str, str]) -> Anchor:
    """The qualified name a `before` template's call is of: a dotted name as written
    (`pydantic.parse_obj_as(...)`), or `$m.member(...)` with `where` naming the class of `$m`."""
    call = before.tree
    if not isinstance(call, cst.Call):
        raise TemplateError("is no call; a pattern is a call of a name")
    func = call.func
    if isinstance(func, cst.Attribute) and (receiver := _meta(func.value)) is not None:
        if receiver not in where:
            raise TemplateError(f"calls a member of ${receiver}, whose class `where` does not name")
        return Anchor(f"{where[receiver]}.{func.attr.value}", receiver)
    name = dotted(func)
    if name.count(".") < 1 or any(part.startswith(_PREFIX) for part in name.split(".")):
        raise TemplateError("calls something that is not a qualified name such as `lib.name`")
    return Anchor(name, None)


def new_names(template: Template) -> set[str]:
    """The names a template spells out, as dotted chains (`pydantic.TypeAdapter`): the roots that
    are neither a metavariable, a pure builtin nor `None`, `True` or `False`, which need no import;
    the rest would."""
    return set(template.spelled)


def _spelled(node: cst.BaseExpression, found: set[str]) -> None:
    name = dotted(node)
    if name:
        root = name.partition(".")[0]
        if _meta(cst.Name(root)) is None and root not in PURE | CONSTANTS:
            found.add(name)
    elif isinstance(node, cst.Attribute):
        _spelled(node.value, found)
    elif isinstance(node, cst.Call):
        _spelled(node.func, found)
        for argument in node.args:
            _spelled(argument.value, found)
    elif isinstance(node, cst.Subscript):
        _spelled(node.value, found)
        # A template holds one index in a subscript.
        _spelled(cast("cst.Index", node.slice[0].slice).value, found)
    elif isinstance(node, cst.Tuple | cst.List):
        # A template holds no starred element, so every element has a value to read.
        for item in node.elements:
            _spelled(cast("cst.Element", item).value, found)
    elif isinstance(node, cst.Dict):
        for entry in node.elements:
            _spelled(cast("cst.DictElement", entry).key, found)
            _spelled(cast("cst.DictElement", entry).value, found)
    elif isinstance(node, cst.UnaryOperation):
        _spelled(node.expression, found)


def pure(node: cst.BaseExpression) -> bool:
    """Whether evaluating an expression twice, or not at all, is no different from once: a name, an
    attribute of one, a number or a string."""
    if isinstance(node, cst.Name | cst.Integer | cst.Float | cst.SimpleString):
        return True
    if isinstance(node, cst.Attribute):
        return pure(node.value)
    return isinstance(node, cst.UnaryOperation) and isinstance(
        node.expression, cst.Integer | cst.Float
    )


def match(
    before: Template, call: cst.Call, *, spelled: bool
) -> dict[str, cst.BaseExpression] | None:
    """What the template's metavariables are bound to where `call` has the template's form, else
    `None`. With `spelled` the callee is compared by name (`$m.member` binds `$m`); without, it is
    not compared, since the scan found it by its qualified name and not by how it is written."""
    pattern = before.tree
    assert isinstance(pattern, cst.Call)  # noqa: S101 - `anchor` has checked it
    bound: dict[str, cst.BaseExpression] = {}
    if spelled:
        func, written = pattern.func, call.func
        if not (
            isinstance(func, cst.Attribute)
            and isinstance(written, cst.Attribute)
            and func.attr.value == written.attr.value
            and _bind(func.value, written.value, bound)
        ):
            return None
    return bound if _arguments(pattern.args, call.args, bound) else None


def _arguments(
    wanted: Sequence[cst.Arg], given: Sequence[cst.Arg], bound: dict[str, cst.BaseExpression]
) -> bool:
    if any(argument.star for argument in given):
        return False
    first = [argument for argument in wanted if argument.keyword is None]
    kept = [argument for argument in given if argument.keyword is None]
    if len(first) != len(kept):
        return False
    named = {argument.keyword.value: argument for argument in wanted if argument.keyword}
    passed = {argument.keyword.value: argument for argument in given if argument.keyword}
    if named.keys() != passed.keys() or len(passed) != len(given) - len(kept):
        return False
    pairs = [*zip(first, kept, strict=True), *((named[key], passed[key]) for key in named)]
    return all(_bind(one.value, other.value, bound) for one, other in pairs)


def _bind(
    pattern: cst.BaseExpression, node: cst.BaseExpression, bound: dict[str, cst.BaseExpression]
) -> bool:
    """Whether `node` has the form `pattern` has, binding each metavariable it meets."""
    name = _meta(pattern)
    if name is not None:
        if name in bound:
            # An expression written twice is one only if running it twice is running it once.
            return pure(node) and _text(bound[name]) == _text(node)
        bound[name] = _held(node)
        return True
    if type(pattern) is not type(node):
        return False
    match pattern:
        case cst.Name():
            return pattern.value == cast("cst.Name", node).value
        case cst.Attribute():
            other = cast("cst.Attribute", node)
            return pattern.attr.value == other.attr.value and _bind(
                pattern.value, other.value, bound
            )
        case cst.Integer() | cst.Float():
            return pattern.value == cast("cst.Integer | cst.Float", node).value
        case cst.SimpleString():
            return pattern.evaluated_value == cast("cst.SimpleString", node).evaluated_value
        case cst.Call():
            other_call = cast("cst.Call", node)
            return _bind(pattern.func, other_call.func, bound) and _arguments(
                pattern.args, other_call.args, bound
            )
        case cst.Tuple() | cst.List():
            other_seq = cast("cst.Tuple | cst.List", node)
            return len(pattern.elements) == len(other_seq.elements) and all(
                isinstance(one, cst.Element)
                and isinstance(two, cst.Element)
                and _bind(one.value, two.value, bound)
                for one, two in zip(pattern.elements, other_seq.elements, strict=True)
            )
        case cst.Dict():
            other_dict = cast("cst.Dict", node)
            return len(pattern.elements) == len(other_dict.elements) and all(
                isinstance(one, cst.DictElement)
                and isinstance(two, cst.DictElement)
                and _bind(one.key, two.key, bound)
                and _bind(one.value, two.value, bound)
                for one, two in zip(pattern.elements, other_dict.elements, strict=True)
            )
        case cst.Subscript():
            other_sub = cast("cst.Subscript", node)
            return (
                len(pattern.slice) == len(other_sub.slice) == 1
                and isinstance(pattern.slice[0].slice, cst.Index)
                and isinstance(other_sub.slice[0].slice, cst.Index)
                and other_sub.slice[0].slice.star is None
                and _bind(pattern.value, other_sub.value, bound)
                and _bind(pattern.slice[0].slice.value, other_sub.slice[0].slice.value, bound)
            )
        case cst.UnaryOperation():
            other_op = cast("cst.UnaryOperation", node)
            return type(pattern.operator) is type(other_op.operator) and _bind(
                pattern.expression, other_op.expression, bound
            )
    return False  # pragma: no cover - the forms of a template are the ones above


def _held(node: cst.BaseExpression) -> cst.BaseExpression:
    """An expression kept to be written elsewhere, in parentheses where its own call's brackets
    were what held it together: a generator as the one argument, a walrus, a `yield`."""
    if isinstance(node, cst.GeneratorExp | cst.NamedExpr | cst.Yield) and not node.lpar:
        return node.with_changes(lpar=[cst.LeftParen()], rpar=[cst.RightParen()])
    return node


def _text(node: cst.CSTNode) -> str:
    return cst.Module(body=[]).code_for_node(node).strip()


def build(
    after: Template,
    bound: Mapping[str, cst.BaseExpression],
    spelled: Mapping[str, cst.BaseExpression] | None = None,
) -> cst.BaseExpression:
    """The `after` template over what `before` bound. A name the template spells out beneath a path
    in `spelled` is written with the expression the file spelled that path with."""
    built = after.tree.visit(_Build(bound, spelled or {}))
    return cast("cst.BaseExpression", built)


class _Build(cst.CSTTransformer):
    def __init__(
        self, bound: Mapping[str, cst.BaseExpression], spelled: Mapping[str, cst.BaseExpression]
    ):
        super().__init__()
        self._bound = bound
        self._spelled = spelled
        self._inserted: set[int] = set()

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> cst.BaseExpression:
        name = _meta(original_node)
        if name is None:
            return updated_node
        self._inserted.add(id(self._bound[name]))
        return self._bound[name]

    def leave_Attribute(
        self, original_node: cst.Attribute, updated_node: cst.Attribute
    ) -> cst.BaseExpression:
        spelled = self._spelled.get(dotted(original_node.value))
        value = updated_node.value if spelled is None else spelled
        return updated_node.with_changes(value=self._atom(value))

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
        return updated_node.with_changes(func=self._atom(updated_node.func))

    def leave_Subscript(
        self, original_node: cst.Subscript, updated_node: cst.Subscript
    ) -> cst.BaseExpression:
        return updated_node.with_changes(value=self._atom(updated_node.value))

    def _atom(self, node: cst.BaseExpression) -> cst.BaseExpression:
        """An expression that was put where a name or an attribute is read off it, in parentheses
        unless it is as tight as one."""
        return node if id(node) not in self._inserted or tight(node) else _wrapped(node)

    def leave_UnaryOperation(
        self, original_node: cst.UnaryOperation, updated_node: cst.UnaryOperation
    ) -> cst.BaseExpression:
        return updated_node.with_changes(expression=self._atom(updated_node.expression))


def tight(node: cst.BaseExpression) -> bool:
    """Whether nothing around an expression can change how it reads: it is in parentheses, or is a
    name, an attribute, a call, a subscript, a literal or a bracketed collection."""
    return bool(node.lpar) or isinstance(
        node,
        cst.Name
        | cst.Attribute
        | cst.Call
        | cst.Subscript
        | cst.Integer
        | cst.Float
        | cst.SimpleString
        | cst.List
        | cst.Dict,
    )


def _wrapped(node: cst.BaseExpression) -> cst.BaseExpression:
    return node.with_changes(lpar=[cst.LeftParen()], rpar=[cst.RightParen()])


# Where an expression reads the same as a call did: it is all there is to the statement, the
# right-hand side, a returned value, one argument or one element.
_LOOSE: Final = (
    cst.Expr,
    cst.Assign,
    cst.AnnAssign,
    cst.Return,
    cst.Arg,
    cst.Element,
    cst.DictElement,
)


def place(node: cst.BaseExpression, parent: cst.CSTNode) -> cst.BaseExpression:
    """The expression that takes a call's place, in parentheses unless it is tight, or the call
    stood where any expression reads the same and this one is on a single line. A tuple that is
    not in brackets would run into the arguments or elements around it."""
    if tight(node):
        return node
    alone = isinstance(parent, _LOOSE) and "\n" not in _text(node)
    spare = isinstance(node, cst.Tuple) and isinstance(
        parent, cst.Arg | cst.Element | cst.DictElement
    )
    return node if alone and not spare else _wrapped(node)


__all__ = [
    "CONSTANTS",
    "LIMIT",
    "PURE",
    "Anchor",
    "Template",
    "TemplateError",
    "anchor",
    "build",
    "dotted",
    "match",
    "new_names",
    "parse",
    "place",
    "pure",
    "tight",
]
