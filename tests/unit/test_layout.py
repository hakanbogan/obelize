"""The layout algorithm of `basic/ground_truth.yaml` note 4.

Only a rule that generates arguments can reach the multi-line-argument clause, so it is pinned by
calling `layout.call` directly.
"""

from __future__ import annotations

from pathlib import Path

import acme
import libcst as cst
import pytest

from obelize.packs import loader
from obelize.transforms import layout

ROOT = Path(__file__).resolve().parents[2]
WIDTH = loader.load("gemini/google-generativeai-to-google-genai").pack.layout.line_length

# Every answer key. Read as bytes: in `scan/encoding/` one is latin-1 and one has a UTF-8 BOM.
KEYS = sorted(
    path
    for directory in ("tests/fixtures", "src/obelize/packs", "examples")
    for path in (ROOT / directory).rglob("*.after.py")
)

CALL = cst.ensure_type(cst.parse_expression("f(a)"), cst.Call)


def emit(args: list[cst.Arg], *, width: int = 100, indent: str = "") -> str:
    produced = layout.call(
        CALL,
        cst.Name("g"),
        args,
        indent=indent,
        unit="    ",
        width=width,
        around=0,
    )
    return layout.render(produced)


def test_a_call_whose_arguments_all_fit_is_emitted_on_one_line() -> None:
    assert emit([cst.Arg(value=cst.Name("a"))]) == "g(a)"


def test_a_generated_argument_that_is_multi_line_wraps_the_call_that_holds_it() -> None:
    """The call is one line and under the width, so only the argument can make it wrap."""
    value = cst.parse_expression("[\n    1,\n]")
    assert layout.multiline(value)
    assert emit([layout.keyword("k", value)]) == "g(\n    k=[\n    1,\n],\n)"


def test_the_width_is_measured_over_the_whole_line_and_not_the_expression() -> None:
    """`around` is what the statement puts on the line either side of the call."""
    argument = [layout.keyword("k", cst.Name("a" * 20))]
    assert emit(argument, width=25) == "g(k=" + "a" * 20 + ")"
    assert "\n" in emit(argument, width=24)


def test_the_indent_is_the_statements_own_plus_one_unit() -> None:
    argument = [layout.keyword("k", cst.Name("a"))]
    assert emit(argument, width=1, indent="        ") == "g(\n            k=a,\n        )"


def test_a_statement_that_does_not_start_its_line_is_indented_by_its_column() -> None:
    """`x = 1; ...` has no indentation of its own, and the semicolon must stay."""
    code, edits = acme.transform(
        "import acme.sdk as sdk\n\nx = 1; sdk.configure(key=KEY)\n", acme.CHANGE, acme.CLIENT
    )
    assert code.endswith("x = 1; handle = sdk.Client(key=KEY)\n")
    assert [row.status for row in edits] == ["auto", "auto"]


WRITTEN = """f(  # opening
    # above x
    x=1,  # after x
    # above y
    y=2  # after y
    # tail
)"""


def written(source: str = WRITTEN) -> cst.Call:
    return cst.ensure_type(cst.parse_expression(source), cst.Call)


def rewritten(source: cst.Call, args: list[cst.Arg], *, comments: bool = True) -> str:
    return layout.render(
        layout.call(
            source,
            cst.Name("g"),
            args,
            indent="",
            unit="    ",
            width=100,
            around=0,
            comments=comments,
        )
    )


def test_the_comments_under_a_node_are_listed_in_the_order_they_were_written() -> None:
    assert [found.value for found in layout.comments(written())] == [
        "# opening",
        "# above x",
        "# after x",
        "# above y",
        "# after y",
        "# tail",
    ]


def test_a_comment_beside_a_moved_argument_goes_with_it() -> None:
    """Above it, after it, after the opening parenthesis, and after the last: each where it was."""
    source = written()
    args = [layout.keyword(arg.keyword.value, arg.value) for arg in source.args if arg.keyword]
    assert rewritten(source, args) == (
        "g(\n    # opening\n    # above x\n    x=1,  # after x\n    # above y\n"
        "    y=2,  # after y\n    # tail\n)"
    )


def test_a_comment_follows_the_argument_it_was_written_beside_when_the_order_changes() -> None:
    """A moved argument is found by its value; the one left out takes its comments with it."""
    source = written("f(\n    # above a\n    a=1,  # after a\n    b=2,  # after b\n    c=3,\n)")
    a, _b, c = source.args
    produced = rewritten(
        source,
        [
            layout.keyword("c", c.value),
            layout.keyword("new", cst.Name("z")),
            layout.keyword("a", a.value),
        ],
    )
    assert produced == "g(\n    c=3,\n    new=z,\n    # above a\n    a=1,  # after a\n)"


def test_a_comment_is_not_carried_unless_the_call_replaces_the_one_it_was_written_in() -> None:
    """A copy of an object that stays has its comments where it is."""
    source = written()
    args = [layout.keyword(arg.keyword.value, arg.value) for arg in source.args if arg.keyword]
    assert rewritten(source, args, comments=False) == "g(\n    x=1,\n    y=2,\n)"


def test_a_comment_in_an_empty_call_closes_the_call_that_replaces_it() -> None:
    source = written("f(\n    # nothing yet\n)")
    assert rewritten(source, [layout.keyword("x", cst.Name("v"))]) == (
        "g(\n    x=v,\n    # nothing yet\n)"
    )


def test_what_is_not_a_call_has_no_arguments_to_carry_comments_from() -> None:
    source = cst.parse_expression("{\n    # c\n    'a': 1,\n}")
    produced = layout.call(
        source,
        cst.Name("g"),
        [layout.keyword("a", cst.Integer("1"))],
        indent="",
        unit="    ",
        width=100,
        around=0,
        comments=True,
    )
    assert layout.render(produced) == "g(\n    a=1,\n)"


def test_the_repository_has_the_answer_keys_this_guard_thinks_it_has() -> None:
    """An empty parametrisation would pass silently."""
    assert len(KEYS) >= 20, [path.name for path in KEYS]


@pytest.mark.parametrize("path", KEYS, ids=lambda path: path.name)
def test_no_answer_key_is_wider_than_the_pack_allows(path: Path) -> None:
    """A key wider than the pack allows is one no rule can produce (ADR-026 D7)."""
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:  # one fixture, and it is the point
        text = data.decode("latin-1")
    lines = enumerate(text.splitlines(), 1)
    wide = [(number, len(line)) for number, line in lines if len(line) > WIDTH]
    assert wide == [], f"{path.relative_to(ROOT)} exceeds {WIDTH} columns at {wide}"
