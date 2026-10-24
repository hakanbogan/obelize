"""`rewrite_pattern`: a call rewritten from the shape of its arguments.

The pack is `tests/packs/generic/acme/shapes-1-to-2`: `make_square(n)` is `Square(side=n)`, and
`Shape.render(w)` is `Shape.draw(width=w)` on an instance of a class derived from `Shape`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import acme
import pytest

from obelize.models import Edit, ScanSpec
from obelize.packs import loader
from obelize.packs.schema import PackDocument, RewritePatternChange
from obelize.transforms.kinds.rewrite_pattern import RewritePattern

PACK = Path(__file__).resolve().parents[1] / "packs" / "generic" / "acme" / "shapes-1-to-2"
LOADED = loader.load(str(PACK / "pack.yaml"))
SPEC = loader.to_scan_spec(LOADED)
CHANGES = {
    change.id: change for change in LOADED.pack.changes if isinstance(change, RewritePatternChange)
}
CALLS, MEMBERS = CHANGES["rewrite-calls"], CHANGES["rewrite-members"]
HEAD = "import acme.shapes\nimport acme.shapes as shapes\nfrom acme.shapes import Shape\n\n\n"
HEAD += "class Square(Shape):\n    pass\n\n\n"


def tidy(
    source: str, change: RewritePatternChange = CALLS, spec: ScanSpec = SPEC
) -> tuple[str, list[Edit]]:
    return acme.transform(source, change, spec=spec)


def pattern_change(**params: Any) -> RewritePatternChange:
    return RewritePatternChange.model_validate(
        {
            "id": "other",
            "kind": "rewrite_pattern",
            "citation": "Acme Shapes 2 notes",
            "fixtures": ["fixtures/negative/a.py", "fixtures/positive/b.before.py"],
            "params": params,
        }
    )


@pytest.mark.parametrize(
    ("body", "written"),
    [
        ("acme.shapes.make_square(2)", "acme.shapes.Square(side=2)"),
        ("shapes.make_square(n + 1)", "shapes.Square(side=n + 1)"),
        ("x = [shapes.make_square(m) for m in ms]", "x = [shapes.Square(side=m) for m in ms]"),
        ("shapes.make_square(shapes.make_square(1))", "shapes.Square(side=shapes.Square(side=1))"),
    ],
)
def test_a_call_of_a_written_name_is_rewritten_over_its_arguments(body: str, written: str) -> None:
    code, edits = tidy(HEAD + body + "\n")
    assert code == HEAD + written + "\n"
    assert {(row.status, row.rule_id) for row in edits} == {("auto", "rewrite-calls")}


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("acme.shapes.make_square(2, extra=1)", "pattern_unmatched"),
        ("acme.shapes.make_square()", "pattern_unmatched"),
        ("acme.shapes.make_square(*rest)", "pattern_unmatched"),
        ("acme.shapes.make_square(n=2)", "pattern_unmatched"),
    ],
)
def test_a_call_of_another_shape_is_left_for_a_person(body: str, reason: str) -> None:
    source = HEAD + body + "\n"
    code, edits = tidy(source)
    assert code == source
    assert [(row.status, row.reason) for row in edits] == [("needs_review", reason)]


def test_a_call_of_a_name_written_without_its_module_has_no_module_to_spell_the_new_name_by() -> (
    None
):
    source = "from acme.shapes import make_square\n\nmake_square(2)\n"
    code, edits = tidy(source)
    assert code == source
    assert [(row.status, row.reason) for row in edits] == [
        ("needs_review", "from_import_unmigrated_symbol")
    ]


def test_a_new_expression_that_spells_no_name_needs_no_module_to_spell_it_by() -> None:
    change = pattern_change(before="acme.shapes.size($n)", after="int($n)")
    spec = SPEC.model_copy(update={"symbols": (*SPEC.symbols, "acme.shapes.size")})
    code, edits = tidy("from acme.shapes import size\n\nsize('3')\n", change, spec)
    assert code == "from acme.shapes import size\n\nint('3')\n"
    assert [row.status for row in edits] == ["auto"]


@pytest.mark.parametrize(
    ("body", "written"),
    [
        ("item.render(3)", "item.draw(width=3)"),
        ("Square().render(width_of(item))", "Square().draw(width=width_of(item))"),
        ("(w + 1).render(w)", "(w + 1).render(w)"),
    ],
)
def test_a_call_of_a_member_on_a_typed_receiver_is_rewritten_over_what_it_is_made_on(
    body: str, written: str
) -> None:
    source = HEAD + f"def f(item: Square, w):\n    return {body}\n"
    code, edits = tidy(source, MEMBERS)
    assert code == source.replace(body, written)
    assert {row.rule_id for row in edits} <= {"rewrite-members"}


def test_a_call_on_self_is_rewritten_too() -> None:
    source = HEAD + "class Ring(Square):\n    def f(self, w):\n        return self.render(w)\n"
    code, _edits = tidy(source, MEMBERS)
    assert code.endswith("return self.draw(width=w)\n")


def test_a_member_call_of_another_shape_is_left_for_a_person() -> None:
    source = HEAD + "def f(item: Square):\n    return item.render(width=3), item.render(1, 2)\n"
    code, edits = tidy(source, MEMBERS)
    assert code == source
    assert {(row.status, row.reason) for row in edits} == {("needs_review", "pattern_unmatched")}


def test_a_member_called_through_the_module_of_its_class_has_no_receiver_to_match() -> None:
    source = HEAD + "acme.shapes.Shape.render(Square(), 3)\n"
    code, edits = tidy(source, MEMBERS)
    assert code == source
    assert [(row.status, row.reason) for row in edits] == [("needs_review", "pattern_unmatched")]


def test_a_member_that_is_read_and_not_called_is_no_call_the_pattern_covers() -> None:
    source = HEAD + "def f(item: Square):\n    return item.render\n"
    code, edits = tidy(source, MEMBERS)
    assert (code, edits) == (source, [])


def test_the_comments_of_the_call_that_goes_stay_above_the_statement() -> None:
    code, _edits = tidy(HEAD + "acme.shapes.make_square(  # why\n    2,\n)\n")
    assert code.endswith("# why\nacme.shapes.Square(side=2)\n")


def test_a_file_with_nothing_the_pattern_is_found_by_reports_nothing() -> None:
    assert tidy("x = 1\n") == ("x = 1\n", [])


def test_the_rule_claims_the_calls_of_its_name_and_nothing_else() -> None:
    rule = RewritePattern(CALLS)
    assert (rule.consumes, rule.client_readers) == (frozenset(), frozenset())
    rows = acme.scan(
        HEAD + "acme.shapes.make_square(2)\nx = acme.shapes.make_square\n", SPEC
    ).findings
    assert [rule.claims(row) for row in rows] == [True, False]


def test_the_scan_reads_the_class_of_a_member_pattern_off_a_receiver() -> None:
    assert SPEC.members_of("acme.shapes.Shape") == ("old_area", "render", "retired", "to_dict")


def test_the_pack_without_a_member_pattern_reads_no_class_for_it() -> None:
    document = LOADED.pack.model_dump(by_alias=True)
    document["changes"] = [one for one in document["changes"] if one["id"] != "rewrite-members"]
    pack = PackDocument.model_validate(document)
    spec = loader.to_scan_spec(
        loader.LoadedPack(
            pack=pack,
            sha256="a" * 64,
            data=b"",
            reference="x",
            bundled=False,
            path=PACK / "pack.yaml",
        )
    )
    assert "render" not in spec.members_of("acme.shapes.Shape")


def only(after: str, before: str = "acme.shapes.make_square($n)") -> RewritePatternChange:
    return pattern_change(before=before, after=after)


@pytest.mark.parametrize(
    ("after", "source", "written"),
    [
        ("$n", "x = acme.shapes.make_square(a or b).strip()", "x = (a or b).strip()"),
        ("$n", "x = 3 * acme.shapes.make_square(a + b)", "x = 3 * (a + b)"),
        ("$n", "x = (acme.shapes.make_square(a if c else d)).real", "x = (a if c else d).real"),
        ("-$n", "x = acme.shapes.make_square(a + b)", "x = -(a + b)"),
        ("not $n", "x = acme.shapes.make_square(a and b)", "x = not (a and b)"),
        ("$n, 1", "y = f(acme.shapes.make_square(a))", "y = f((a, 1))"),
        ("$n", "x = acme.shapes.make_square(\n    a\n    + b\n)", "x = (a\n    + b)"),
        ("$n", "x = acme.shapes.make_square(a)", "x = a"),
        ("[$n]", "x = acme.shapes.make_square(i for i in z)", "x = [(i for i in z)]"),
        (
            "acme.shapes.Square(side=$n)",
            "x = acme.shapes.make_square(y := 1)",
            "x = acme.shapes.Square(side=(y := 1))",
        ),
    ],
)
def test_a_new_expression_that_stands_where_the_call_did_keeps_its_meaning(
    after: str, source: str, written: str
) -> None:
    code, edits = tidy(HEAD + source + "\n", only(after))
    assert code == HEAD + written + "\n"
    assert {row.status for row in edits} == {"auto"}


@pytest.mark.parametrize(
    ("before", "after", "source"),
    [
        # An expression that is run twice, or never, where it was run once.
        (
            "acme.shapes.make_square($n)",
            "acme.shapes.Square(side=$n, area=$n)",
            "acme.shapes.make_square(next(it))",
        ),
        (
            "acme.shapes.make_square($n, $k)",
            "acme.shapes.Square(side=$n)",
            "acme.shapes.make_square(a, log())",
        ),
        (
            "acme.shapes.make_square($n, $n)",
            "acme.shapes.Square(side=$n)",
            "acme.shapes.make_square(next(it), next(it))",
        ),
    ],
)
def test_an_expression_the_new_call_runs_twice_or_never_is_left_for_a_person(
    before: str, after: str, source: str
) -> None:
    text = HEAD + source + "\n"
    code, edits = tidy(text, only(after, before))
    assert code == text
    assert [(row.status, row.reason) for row in edits] == [("needs_review", "pattern_unmatched")]


@pytest.mark.parametrize(
    ("after", "source", "written"),
    [
        (
            "acme.shapes.Square(side=$n, area=$n)",
            "acme.shapes.make_square(width)",
            "acme.shapes.Square(side=width, area=width)",
        ),
        (
            "acme.shapes.Square(side=3)",
            "acme.shapes.make_square(width)",
            "acme.shapes.Square(side=3)",
        ),
    ],
)
def test_a_name_may_be_written_twice_or_not_at_all_where_running_it_is_no_difference(
    after: str, source: str, written: str
) -> None:
    code, edits = tidy(HEAD + source + "\n", only(after))
    assert code == HEAD + written + "\n"
    assert [row.status for row in edits] == ["auto"]


def test_a_call_inside_an_f_string_is_left_where_the_new_text_writes_a_string() -> None:
    text = HEAD + 'x = f"{acme.shapes.make_square(a)}"\n'
    quoted = only('acme.shapes.Square(name="a", side=$n)')
    code, edits = tidy(text, quoted)
    assert code == text
    assert [row.reason for row in edits] == ["pattern_unmatched"]
    code, edits = tidy(text, only("acme.shapes.Square(side=$n)"))
    assert code == HEAD + 'x = f"{acme.shapes.Square(side=a)}"\n'
    assert [row.status for row in edits] == ["auto"]


def through(after: str, *imports: str) -> RewritePatternChange:
    return pattern_change(
        before="acme.shapes.make_square($n)", after=after, imports=sorted(imports)
    )


UNITS = through("acme.shapes.Square(side=kit.units.cm($n))", "kit.units")
LADDER = through("acme.shapes.Square(side=kit.units.cm($n))", "kit", "kit.units")
BASE = "import acme.shapes\n"


@pytest.mark.parametrize(
    ("head", "written"),
    [
        ("import kit.units\n", "kit.units.cm(2)"),
        ("import kit.units as u\n", "u.cm(2)"),
        ("from kit import units\n", "units.cm(2)"),
        ("from kit import units as u\n", "u.cm(2)"),
    ],
)
def test_a_name_is_spelled_through_the_import_the_file_has_of_the_path(
    head: str, written: str
) -> None:
    code, edits = tidy(f"{BASE}{head}\nx = acme.shapes.make_square(2)\n", UNITS)
    assert code == f"{BASE}{head}\nx = acme.shapes.Square(side={written})\n"
    assert [row.status for row in edits] == ["auto"]


def test_a_path_the_file_does_not_import_is_imported_below_the_last_import_above_the_call() -> None:
    code, edits = tidy(f"{BASE}import os\n\nx = acme.shapes.make_square(2)\n", UNITS)
    assert code == (
        f"{BASE}import os\nfrom kit import units\n\nx = acme.shapes.Square(side=units.cm(2))\n"
    )
    assert [row.status for row in edits] == ["auto"]


def test_every_call_of_a_file_shares_the_one_import_it_needs() -> None:
    source = f"{BASE}\nx = acme.shapes.make_square(2)\ny = acme.shapes.make_square(3)\n"
    code, edits = tidy(source, UNITS)
    assert code.count("from kit import units") == 1
    assert code.endswith("Square(side=units.cm(2))\ny = acme.shapes.Square(side=units.cm(3))\n")
    assert [row.status for row in edits] == ["auto", "auto"]


def test_a_name_that_needs_no_module_of_the_call_is_written_for_a_name_imported_bare() -> None:
    """Nothing is spelled beside the called name, so a call written without its module is fine."""
    change = through("kit.units.cm($n)", "kit.units")
    code, edits = tidy("from acme.shapes import make_square\n\nx = make_square(2)\n", change)
    assert code == (
        "from acme.shapes import make_square\nfrom kit import units\n\nx = units.cm(2)\n"
    )
    assert [row.status for row in edits] == ["auto"]


@pytest.mark.parametrize(
    ("head", "added", "written"),
    [
        ("import kit\n", "", "kit.units.cm(2)"),
        ("import kit as k\n", "", "k.units.cm(2)"),
        ("from kit import units\n", "", "units.cm(2)"),
        ("", "from kit import units\n", "units.cm(2)"),
    ],
)
def test_the_first_listed_path_the_file_has_is_used_else_the_longest_is_imported(
    head: str, added: str, written: str
) -> None:
    code, edits = tidy(f"{BASE}{head}\nx = acme.shapes.make_square(2)\n", LADDER)
    assert code == f"{BASE}{head}{added}\nx = acme.shapes.Square(side={written})\n"
    assert [row.status for row in edits] == ["auto"]


@pytest.mark.parametrize(
    "source",
    [
        # A parameter hides the name the new import would take.
        f"{BASE}\ndef f(units):\n    return acme.shapes.make_square(units)\n",
        # A name the file binds to something else.
        f"{BASE}units = 3\nx = acme.shapes.make_square(units)\n",
        # The path is imported, and the name is bound again in a function.
        f"{BASE}from kit import units\n\n\ndef f(units):\n    return acme.shapes.make_square(1)\n",
    ],
)
def test_a_name_that_is_shadowed_leaves_the_call_for_a_person(source: str) -> None:
    code, edits = tidy(source, UNITS)
    assert code == source
    assert [(row.status, row.reason) for row in edits] == [("needs_review", "alias_collision")]


def test_a_file_that_imports_only_inside_functions_has_no_line_for_the_new_import() -> None:
    source = "def f():\n    import acme.shapes\n    return acme.shapes.make_square(2)\n"
    code, edits = tidy(source, UNITS)
    assert code == source
    assert [(row.status, row.reason) for row in edits] == [("needs_review", "local_import")]


def test_an_import_that_follows_the_call_does_not_run_before_it() -> None:
    source = "def f():\n    return acme.shapes.make_square(2)\n\n\nimport acme.shapes\n"
    code, edits = tidy(source, UNITS)
    assert code == source
    assert [row.reason for row in edits] == ["local_import"]


def test_a_path_imported_after_the_call_is_not_one_the_call_can_use() -> None:
    source = f"{BASE}x = acme.shapes.make_square(2)\nfrom kit import units\n"
    code, edits = tidy(source, UNITS)
    assert [row.reason for row in edits] == ["alias_collision"]
    assert code == source
