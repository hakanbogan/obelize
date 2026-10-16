"""How a rewritten call or list is laid out.

1. Multi-line when the source was, when an argument is, or when the whole emitted line (indent and
   trailing comment included, as a formatter counts) is wider than the pack's `layout.line_length`.
2. Multi-line is one argument per line, one indent unit (the file's own, as libcst infers it) past
   the indent of the line the call starts on, with a trailing comma and the closer back on that
   indent. That line is the statement's, unless the call sits on a continuation line.
3. Recursive: a nested call is built at the indent the outer call would wrap to.

Wrapping only adds breaks; a call the author split is never joined. A moved argument keeps its
value, keyword and inner comments; the separators belong to the call it lands in, except the
comments written in them: those above an argument and the one after it go with it (`nest`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import libcst as cst
import libcst.matchers as m

if TYPE_CHECKING:
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


def comments(node: cst.CSTNode) -> list[cst.Comment]:
    """Every comment written under `node`, in source order."""
    return [found for found in m.findall(node, m.Comment()) if isinstance(found, cst.Comment)]


def call(
    source: cst.CSTNode | None,
    func: cst.BaseExpression,
    args: list[cst.Arg],
    *,
    indent: str,
    unit: str,
    width: int,
    around: int,
    comments: bool = False,
) -> cst.Call:
    """`func(*args)`, laid out by the three rules above.

    `source` is what the arguments were written in (`None` for an invented call), for clause 1;
    `around` is the width of the rest of the emitted line (`client = `, a trailing comment).
    `comments` carries the ones written between the arguments of `source`, which only a call that
    replaces `source` should: a copy of an object that stays holds them already.
    """
    written = source if isinstance(source, cst.Call) else None
    flat = (written or cst.Call(func=func)).with_changes(
        func=func, args=args, whitespace_before_args=cst.SimpleWhitespace("")
    )
    if not _wraps(source, args, flat, indent=indent, width=width, around=around):
        return flat
    return nest(flat, written if comments else None, indent=indent, unit=unit)


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


def nest(target: cst.Call, written: cst.Call | None, *, indent: str, unit: str) -> cst.Call:
    """`target` with one argument per line, one unit past `indent`.

    `written` is the call its arguments were written in. A comment on a line of its own above one
    of them goes above it here, and one ending its line goes after it; any other is not placed.
    """
    breaks = _breaks(written, target.args, indent, indent + unit)
    return target.with_changes(
        whitespace_before_args=breaks[0],
        args=[
            argument.with_changes(
                comma=cst.Comma(whitespace_after=after),
                whitespace_after_arg=cst.SimpleWhitespace(""),
            )
            for argument, after in zip(target.args, breaks[1:], strict=True)
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


def _break(
    indent: str,
    *,
    trailing: cst.Comment | None = None,
    lines: Sequence[cst.Comment] = (),
    at: str = "",
) -> cst.ParenthesizedWhitespace:
    """A newline followed by exactly `indent`, with no blank line between.

    `trailing` ends the line before it; `lines` are comment lines at `at` in between.
    """
    return cst.ParenthesizedWhitespace(
        first_line=cst.TrailingWhitespace(
            whitespace=cst.SimpleWhitespace("  " if trailing else ""),
            comment=trailing,
            newline=cst.Newline(),
        ),
        empty_lines=[
            cst.EmptyLine(indent=False, whitespace=cst.SimpleWhitespace(at), comment=line)
            for line in lines
        ],
        indent=False,
        last_line=cst.SimpleWhitespace(indent),
    )


def _breaks(
    written: cst.Call | None, args: Sequence[cst.Arg], indent: str, inside: str
) -> list[cst.ParenthesizedWhitespace]:
    """The separator before the first of `args`, then the one after each: a break, with comments.

    An argument is found in `written` by its value, which a moved argument keeps. It takes the
    comments on lines of their own above it (the one after the opening parenthesis too) and the
    one ending its line. The lines of their own after the last argument written close the call.
    """
    notes: dict[int, tuple[list[cst.Comment], cst.Comment | None]] = {}
    tail: list[cst.Comment] = []
    if written is not None:
        spaces = [written.whitespace_before_args, *map(_after, written.args)]
        for index, argument in enumerate(written.args):
            ends, lines = _lines(spaces[index])
            above = [ends, *lines] if ends and not index else lines
            notes[id(argument.value)] = (above, _lines(spaces[index + 1])[0])
        tail = _lines(spaces[-1])[1]
    held = [notes.get(id(argument.value), ([], None)) for argument in args]
    above_each = [*(above for above, _ in held), tail]
    ends_each = [None, *(ends for _, ends in held)]
    return [
        _break(inside if index < len(args) else indent, trailing=ends, lines=above, at=inside)
        for index, (above, ends) in enumerate(zip(above_each, ends_each, strict=True))
    ]


def _after(argument: cst.Arg) -> cst.BaseParenthesizableWhitespace:
    """What the author wrote between `argument` and whatever follows it."""
    comma = argument.comma
    return comma.whitespace_after if isinstance(comma, cst.Comma) else argument.whitespace_after_arg


def _lines(
    space: cst.BaseParenthesizableWhitespace,
) -> tuple[cst.Comment | None, list[cst.Comment]]:
    """The comment ending the line `space` starts on, and the comments on lines of their own."""
    if not isinstance(space, cst.ParenthesizedWhitespace):
        return None, []
    return space.first_line.comment, [line.comment for line in space.empty_lines if line.comment]


def _tagged[Part: (cst.Arg, cst.BaseElement)](parts: Sequence[Part]) -> list[tuple[Part, bool]]:
    """Each argument or list element, and whether it is the last."""
    return [(part, index == len(parts) - 1) for index, part in enumerate(parts)]


def indent_of(lines: Sequence[str], line: int, column: int) -> str:
    """The source's indent for the statement at `line`, `column` (tabs stay tabs).

    A statement that does not start its line (`x = 1; genai.configure(...)`) gets `column` spaces.
    """
    text = lines[line - 1][:column]
    return text if not text.strip() else " " * column
