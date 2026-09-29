"""One metadata resolve per file, shared by every rule that replaces a call.

Resolving again would cost 17-30% of a file's scan time, and two indexes from one wrapper could
disagree about which of two calls at one position the scanner found.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import libcst as cst
import libcst.matchers as m
from libcst._metadata_dependent import LazyValue
from libcst.metadata import ParentNodeProvider, PositionProvider, QualifiedNameProvider

from obelize.transforms import layout

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from collections.abc import Iterator, Sequence

    from libcst.metadata import ProviderT

    from obelize.transforms.base import RuleContext

# Where a node starts; a finding and the call it names share it, so the index is keyed on it.
Position = tuple[int, int]


class Tree:
    """The calls of one file, the statements around them, and their layout."""

    def __init__(self, context: RuleContext, extra: Sequence[ProviderT] = ()) -> None:
        context.wrapper.resolve_many([PositionProvider, ParentNodeProvider, *extra])
        self._pos = context.wrapper.resolve(PositionProvider)
        self._parent = context.wrapper.resolve(ParentNodeProvider)
        self._wrapper = context.wrapper
        self.module = context.module
        self._calls: dict[Position, cst.Call] = {}
        for node, span in self._pos.items():
            if isinstance(node, cst.Call):
                self._record(
                    node,
                    (span.start.line, span.start.column),
                    (span.end.line, span.end.column),
                )

    def _record(self, node: cst.Call, start: Position, end: Position) -> None:
        """Keep the innermost call starting here (in `configure(k)(x)`, the scanner's is inner).

        Compare whole end positions, not lines, or same-line calls resolve by dict order. No
        qualified-name filter: a callee reached through a call never resolves to a module attribute.
        """
        held = self._calls.get(start)
        if held is None or end < self.end(held):
            self._calls[start] = node

    def start(self, node: cst.CSTNode) -> Position:
        span = self._pos[node].start
        return (span.line, span.column)

    def end(self, node: cst.CSTNode) -> Position:
        span = self._pos[node].end
        return (span.line, span.column)

    def call(self, position: Position) -> cst.Call:
        """The call a finding names. A finding names one, because a scan found it."""
        return self._calls[position]

    def inside(self, outer: cst.CSTNode, position: Position) -> bool:
        """Whether something starting at `position` is written inside `outer`."""
        return self.start(outer) <= position <= self.end(outer)

    def parent(self, node: cst.CSTNode) -> cst.CSTNode:
        return self._parent[node]

    def qualified(self, node: cst.CSTNode) -> str:
        """The one qualified name, resolved lazily; `""` for none or several (already withheld)."""
        value = self._wrapper.resolve(QualifiedNameProvider).get(node, ())
        names = {name.name for name in (value() if isinstance(value, LazyValue) else value)}
        return names.pop() if len(names) == 1 else ""

    def handlers(self, node: cst.CSTNode) -> Iterator[cst.ExceptHandler]:
        """The `except` clauses of every `try` whose body holds `node`, innermost first.

        Stops at the enclosing function; a `try` guards only its body, not its `else`.
        """
        current = node
        while not isinstance(current, cst.Module | cst.FunctionDef | cst.Lambda | cst.ClassDef):
            parent = self._parent[current]
            if isinstance(parent, cst.Try) and current is parent.body:
                yield from parent.handlers
            current = parent

    def caught(self, node: cst.CSTNode, modules: frozenset[str]) -> bool:
        """Whether a handler around `node` names an exception of one of `modules`.

        The new SDK raises `google.genai.errors`, so a legacy `google.api_core.exceptions` handler
        compiles and never runs.
        """
        return any(
            within(self.qualified(name), modules)
            for handler in self.handlers(node)
            if handler.type is not None
            for name in m.findall(handler.type, m.Name() | m.Attribute())
        )

    def consumer(self, node: cst.CSTNode) -> cst.CSTNode:
        """What takes the value `node` evaluates to, looking through an `await` around it."""
        parent = self._parent[node]
        return self._parent[parent] if isinstance(parent, cst.Await) else parent

    def statement_of(self, node: cst.CSTNode) -> cst.CSTNode:
        """The innermost simple or compound statement holding `node` (a `for` header: the `for`)."""
        current = node
        while not isinstance(current, (cst.SimpleStatementLine, cst.BaseCompoundStatement)):
            current = self._parent[current]
        return current

    def line_of(self, node: cst.CSTNode) -> cst.SimpleStatementLine | None:
        """The simple statement line `node` is written on, if it is on one."""
        statement = self.statement_of(node)
        return statement if isinstance(statement, cst.SimpleStatementLine) else None

    def indent(self, node: cst.CSTNode) -> str:
        """The characters indenting the statement `node` belongs to."""
        start = self._pos[self.statement_of(node)].start
        return layout.indent_of(self.module, start.line, start.column)

    def around(self, call: cst.Call) -> int:
        """How many characters of `call`'s source line are not the call or its indent.

        The rest (`return `, a comment) survives the in-place rewrite. Zero for a multi-line call,
        which wraps anyway.
        """
        start, end = self.start(call), self.end(call)
        if start[0] != end[0]:
            return 0
        text = self.module.code.splitlines()[start[0] - 1]
        return len(text) - (end[1] - start[1]) - len(self.indent(call))

    def trailing(self, node: cst.CSTNode) -> int:
        """How many characters of `node`'s line come after the statement; zero on no simple line."""
        line = self.line_of(node)
        if line is None:  # pragma: no cover - only asked about statements on a line
            return 0
        after = line.trailing_whitespace
        return len(after.whitespace.value) + (len(after.comment.value) if after.comment else 0)


def within(name: str, modules: frozenset[str]) -> bool:
    """Whether the qualified `name` is one of `modules` or something in one."""
    return any(name == module or name.startswith(f"{module}.") for module in modules)


def literal_string(node: cst.BaseExpression) -> str | None:
    """The string a node *is*; `None` for anything else, f-strings and concatenations included."""
    if not isinstance(node, cst.SimpleString):
        return None
    value = node.evaluated_value
    return value if isinstance(value, str) else None


__all__ = ["Position", "Tree", "literal_string"]
