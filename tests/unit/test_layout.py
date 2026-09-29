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


def test_the_repository_has_the_answer_keys_this_guard_thinks_it_has() -> None:
    """An empty parametrisation would pass silently."""
    assert len(KEYS) >= 20, [path.name for path in KEYS]


@pytest.mark.parametrize("path", KEYS, ids=lambda path: path.name)
def test_no_answer_key_is_wider_than_the_pack_allows(path: Path) -> None:
    """A key wider than the pack allows is one no rule can produce (ADR-026 D7)."""
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:  # pragma: no cover - one fixture, and it is the point
        text = data.decode("latin-1")
    lines = enumerate(text.splitlines(), 1)
    wide = [(number, len(line)) for number, line in lines if len(line) > WIDTH]
    assert wide == [], f"{path.relative_to(ROOT)} exceeds {WIDTH} columns at {wide}"
