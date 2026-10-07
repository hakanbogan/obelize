"""How a rewritten call or list is laid out.

1. Multi-line when the source was, when an argument is, or when the whole emitted line (indent and
   trailing comment included, as a formatter counts) is wider than the pack's `layout.line_length`.
2. Multi-line is one argument per line, one indent unit (the file's own, as libcst infers it) past
   the statement's indent, with a trailing comma and the closer back on the statement's indent.
3. Recursive: a nested call is built at the indent the outer call would wrap to.

Wrapping only adds breaks; a call the author split is never joined. A moved argument keeps its
value, keyword and inner comments; the separators belong to the call it lands in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import libcst as cst

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from collections.abc import Sequence

# An empty module to render with; `code_for_node` is exact, so a width is the written bytes'.
_RENDER: Final[cst.Module] = cst.Module(body=())


def render(node: cst.CSTNode) -> str:
    """The source `node` would be written as, with nothing around it."""
    return _RENDER.code_for_node(node)


def keyword(name: str, value: cst.BaseExpression) -> cst.Arg:
    """`name=value` for a generated argument (a built `Arg` renders `name = value` by default)."""
    return cst.Arg(
        value=value,
        keyword=cst.Name(name),
        equal=cst.AssignEqual(
            whitespace_before=cst.SimpleWhitespace(""),
            whitespace_after=cst.SimpleWhitespace(""),
        ),
    )


def multiline(node: cst.CSTNode) -> bool:
    """Whether `node` is written across more than one line."""
    return "\n" in render(node)


def call(
    source: cst.CSTNode | None,
    func: cst.BaseExpression,
    args: list[cst.Arg],
    *,
    indent: str,
    unit: str,
    width: int,
    around: int,
) -> cst.Call:
    """`func(*args)`, laid out by the three rules above.

    `source` is what the arguments were written in (`None` for an invented call), for clause 1;
    `around` is the width of the rest of the emitted line (`client = `, a trailing comment).
    """
    base = source if isinstance(source, cst.Call) else cst.Call(func=func)
    flat = base.with_changes(func=func, args=args, whitespace_before_args=cst.SimpleWhitespace(""))
    if not _wraps(source, args, flat, indent=indent, width=width, around=around):
        return flat
    return nest(flat, indent=indent, unit=unit)


def sequence(
    source: cst.CSTNode | None,
    elements: list[cst.BaseExpression],
    *,
    indent: str,
    unit: str,
    width: int,
    around: int,
) -> cst.List:
    """`[*elements]` laid out like a call; elements are built, so `source` decides only the wrap."""
    flat = cst.List(elements=[cst.Element(value=value) for value in elements])
    if not _wraps(source, elements, flat, indent=indent, width=width, around=around):
        return flat
    inner, closing = _break(indent + unit), _break(indent)
    # The last comma carries the break, as in `nest`; setting the bracket's too writes it twice.
    return flat.with_changes(
        lbracket=cst.LeftSquareBracket(whitespace_after=inner),
        elements=[
            element.with_changes(comma=cst.Comma(whitespace_after=closing if last else inner))
            for element, last in _tagged(flat.elements)
        ],
    )


def nest(target: cst.Call, *, indent: str, unit: str) -> cst.Call:
    """`target` with one argument per line, one unit past `indent`."""
    inner = _break(indent + unit)
    closing = _break(indent)
    return target.with_changes(
        whitespace_before_args=inner,
        args=[
            argument.with_changes(
                comma=cst.Comma(whitespace_after=closing if last else inner),
                whitespace_after_arg=cst.SimpleWhitespace(""),
            )
            for argument, last in _tagged(target.args)
        ],
    )


def _wraps(
    source: cst.CSTNode | None,
    parts: Sequence[cst.CSTNode],
    flat: cst.CSTNode,
    *,
    indent: str,
    width: int,
    around: int,
) -> bool:
    """Clause 1, in its stated order."""
    if source is not None and multiline(source):
        return True
    if any(multiline(part) for part in parts):
        return True
    return len(indent) + len(render(flat)) + around > width


def _break(indent: str) -> cst.ParenthesizedWhitespace:
    """A newline followed by exactly `indent`, with no blank line between."""
    return cst.ParenthesizedWhitespace(
        first_line=cst.TrailingWhitespace(newline=cst.Newline()),
        empty_lines=(),
        indent=False,
        last_line=cst.SimpleWhitespace(indent),
    )


def _tagged[Part: (cst.Arg, cst.BaseElement)](parts: Sequence[Part]) -> list[tuple[Part, bool]]:
    """Each argument or list element, and whether it is the last."""
    return [(part, index == len(parts) - 1) for index, part in enumerate(parts)]


def indent_of(lines: Sequence[str], line: int, column: int) -> str:
    """The source's indent for the statement at `line`, `column` (tabs stay tabs).

    A statement that does not start its line (`x = 1; genai.configure(...)`) gets `column` spaces.
    """
    text = lines[line - 1][:column]
    return text if not text.strip() else " " * column
