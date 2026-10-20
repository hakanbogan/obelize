"""`rename_member`: `Shape.old_area` is `Shape.area` on an instance of a class derived from `Shape`.

The pack is `tests/packs/generic/acme/shapes-1-to-2`, an invented library whose 2.x renamed two
methods of a class that programs derive their own from. The scan types a receiver from what the
file says and leaves any other alone.
"""

from __future__ import annotations

from pathlib import Path

import acme
import libcst as cst
import pytest
from shapes import BINDINGS, UNBOUND

from obelize.models import Edit, ImpactPlan, MemberClass, ScanSpec
from obelize.packs import loader
from obelize.packs.schema import RenameMemberChange
from obelize.scan import analysis
from obelize.transforms import base
from obelize.transforms.kinds.rename_member import RenameMember

PACK = Path(__file__).resolve().parents[1] / "packs" / "generic" / "acme" / "shapes-1-to-2"
LOADED = loader.load(str(PACK / "pack.yaml"))
SPEC = loader.to_scan_spec(LOADED)
(RENAME,) = [change for change in LOADED.pack.changes if isinstance(change, RenameMemberChange)]
BASE = "acme.shapes.Shape"
HEAD = "from acme.shapes import Shape\n\n\nclass Square(Shape):\n    pass\n\n\n"
# A second library class, for a class that derives from both.
TWO = SPEC.model_copy(
    update={
        "member_classes": (
            *SPEC.member_classes,
            MemberClass(class_symbol="acme.shapes.Solid", members=("spin",)),
        )
    }
)


def found(source: str, spec: ScanSpec = SPEC) -> list[tuple[int, str, str, str | None]]:
    """What the scan says of `source`: line, kind, reason and symbol of each row."""
    return acme.rows(acme.scan(source, spec))


def scanned(source: str) -> analysis.Analysis:
    return acme.scan(source, SPEC)


def tidy(source: str) -> tuple[str, list[Edit]]:
    return acme.transform(source, RENAME, spec=SPEC)


def test_the_projection_names_the_class_and_the_members_it_renames_flags_or_rewrites() -> None:
    members = ("old_area", "render", "retired", "to_dict")
    assert SPEC.member_classes == (MemberClass(class_symbol=BASE, members=members),)
    assert SPEC.members_of(BASE) == members
    assert SPEC.members_of("acme.shapes.Other") == ()
    assert (SPEC.constructor_symbols, SPEC.supported_methods) == ((), ())


@pytest.mark.parametrize(
    ("body", "kind", "reason"),
    [
        ("Square().old_area()\n", "method_call", "receiver_typed_by_class"),
        ("Square.to_dict\n", "attribute", "receiver_typed_by_class"),
        ("shape = Square()\nshape.old_area()\n", "method_call", "receiver_bound_same_scope"),
        (
            "shape = Square()\n\n\ndef f():\n    return shape.old_area()\n",
            "method_call",
            "receiver_bound_module_const",
        ),
        (
            "def f(item: Square):\n    item.old_area()\n",
            "method_call",
            "receiver_typed_by_class",
        ),
        (
            "def f(item: 'Square'):\n    item.old_area()\n",
            "method_call",
            "receiver_typed_by_class",
        ),
        (
            "def f(item: Square | None):\n    item.old_area()\n",
            "method_call",
            "receiver_typed_by_class",
        ),
        (
            "def f(item: None | Square):\n    item.old_area()\n",
            "method_call",
            "receiver_typed_by_class",
        ),
        (
            "from typing import Optional\n\n\ndef f(item: Optional[Square]):\n"
            "    item.old_area()\n",
            "method_call",
            "receiver_typed_by_class",
        ),
        (
            "import typing\n\n\ndef f(item: typing.Optional[Square]):\n    item.old_area()\n",
            "method_call",
            "receiver_typed_by_class",
        ),
        (
            "item: Square = make()\nitem.old_area()\n",
            "method_call",
            "receiver_typed_by_class",
        ),
        ("alias = Square\nalias.to_dict\n", "attribute", "receiver_bound_same_scope"),
        (
            "class Ring(Square):\n    def go(self):\n        return self.old_area()\n",
            "method_call",
            "receiver_typed_by_class",
        ),
        (
            "class Ring(Square):\n    @classmethod\n    def go(cls):\n        return cls.to_dict\n",
            "attribute",
            "receiver_typed_by_class",
        ),
    ],
)
def test_a_receiver_the_file_shows_to_be_a_shape_is_found(
    body: str, kind: str, reason: str
) -> None:
    assert [(row[1], row[2], row[3]) for row in found(HEAD + body)] == [
        (kind, reason, f"{BASE}.{'to_dict' if 'to_dict' in body else 'old_area'}")
    ]


@pytest.mark.parametrize(
    "body",
    [
        "def f(item):\n    item.old_area()\n",
        "def f(item: int):\n    item.old_area()\n",
        "def f(item: 'Missing'):\n    item.old_area()\n",
        "def f(item: list[Square]):\n    item.old_area()\n",
        "def f(item: dict[str, Square] | None):\n    item.old_area()\n",
        "def f(item: Square | int):\n    item.old_area()\n",
        "class Other:\n    def f(self):\n        return self.old_area()\n",
        "class Other(Square.Inner):\n    def f(self):\n        return self.old_area()\n",
        "class Ring(Square):\n    @staticmethod\n    def f(item):\n    "
        "    return item.old_area()\n",
        "def f(self):\n    return self.old_area()\n",
        "class Ring(Square):\n    def f(self, other):\n        return other.old_area()\n",
        "class Ring(Square):\n    def f(self, *rest):\n        return rest.old_area()\n",
        "def f():\n    return lambda item: item.old_area()\n",
        "shape = Square()\nshape = make()\nshape.old_area()\n",
        "for shape in [Square()]:\n    shape.old_area()\n",
        "shape = Square()\nshape = None\nshape.old_area()\n",
        "x = make()\nx.old_area()\n",
        "Square().other()\n",
        "Square().child.old_area()\n",
        "make().old_area()\n",
        "x = x\nx.old_area()\n",
    ],
)
def test_a_receiver_nothing_types_is_left_as_it_is(body: str) -> None:
    assert found(HEAD + body) == []


def test_a_name_defined_by_two_classes_of_one_lineage_is_typed_and_of_two_is_not() -> None:
    same = HEAD + "class Square(Shape):\n    pass\n\n\nSquare().old_area()\n"
    assert [row[3] for row in found(same)] == [f"{BASE}.old_area"]
    apart = HEAD + "class Square:\n    pass\n\n\nSquare().old_area()\n"
    assert found(apart) == []


def test_a_name_in_a_string_annotation_is_found_only_where_the_file_defines_one_class_of_it() -> (
    None
):
    twice = (
        HEAD + "class Square(Shape):\n    pass\n\n\ndef f(item: 'Square'):\n    item.old_area()\n"
    )
    assert found(twice) == []


def test_a_class_that_derives_from_itself_has_no_lineage() -> None:
    assert found("class Loop(Loop):\n    pass\n\n\nLoop().old_area()\n") == []


def test_a_class_that_derives_from_two_libraries_is_neither() -> None:
    source = (
        "from acme.shapes import Shape, Solid\n\n\nclass Both(Shape, Solid):\n    pass\n\n\n"
        "Both().spin()\nBoth().old_area()\n"
    )
    assert found(source, TWO) == []


def test_a_member_of_another_class_than_the_receivers_is_not_renamed_on_it() -> None:
    source = HEAD + "Square().spin()\n"
    assert found(source, TWO) == []


@pytest.mark.parametrize(
    "body",
    [
        "class Ring(Square):\n    def old_area(self):\n        return 1\n",
        "class Ring(Square):\n    old_area = None\n",
        "class Ring(Square):\n    old_area: int\n",
        "class Ring(Square):\n    old_area: int = 1\n",
        "class Mixin:\n    def old_area(self):\n        return 1\n\n\n"
        "class Ring(Mixin, Square):\n    pass\n",
        "class Ring(Square, metaclass=type):\n    old_area = None\n",
        "class Ring(Square):\n    class Meta:\n        pass\n\n    old_area = None\n",
    ],
)
def test_a_member_the_repository_defines_is_withheld(body: str) -> None:
    result = scanned(HEAD + body + "\n\nRing().old_area()\n")
    assert acme.statuses(result) == [
        (HEAD.count("\n") + body.count("\n") + 3, "needs_review", "member_overridden")
    ]


def test_a_member_a_class_between_defines_is_carried_down_to_the_classes_below() -> None:
    source = (
        HEAD + "class Ring(Square):\n    def to_dict(self):\n        return {}\n\n\n"
        "class Disc(Ring):\n    pass\n\n\nDisc().to_dict()\nDisc().old_area()\n"
    )
    statuses = [(row[1], row[2]) for row in acme.statuses(scanned(source))]
    assert statuses == [("needs_review", "member_overridden"), ("eligible", None)]


def test_a_star_base_and_a_keyword_base_name_no_class() -> None:
    source = HEAD + "class Ring(*bases, flag=True):\n    pass\n\n\nRing().old_area()\n"
    assert found(source) == []


def test_a_local_class_that_is_no_shape_does_not_hide_one_that_is() -> None:
    source = (
        HEAD
        + "class Plain:\n    pass\n\n\nclass Ring(Plain, Square):\n    pass\n\n\n"
        + "Ring().old_area()\n"
    )
    assert [row[3] for row in found(source)] == [f"{BASE}.old_area"]


def test_a_module_that_is_scanned_by_a_spec_with_no_member_classes_has_no_member_rows() -> None:
    plain = SPEC.model_copy(update={"member_classes": ()})
    assert found(HEAD + "Square().old_area()\n", plain) == []


def test_the_library_chain_is_a_row_of_the_symbol_scan_and_not_of_the_receiver_scan() -> None:
    source = (
        "import acme.shapes\nfrom acme.shapes import Shape\n\n"
        "acme.shapes.Shape.old_area(1)\nShape.to_dict\n"
    )
    assert [row[1] for row in found(source)] == ["call", "attribute"]


@pytest.mark.parametrize(
    ("source", "written"),
    [
        (HEAD + "Square().old_area()\n", HEAD + "Square().area()\n"),
        (HEAD + "x = Square().to_dict\n", HEAD + "x = Square().as_dict\n"),
        (
            HEAD + "shape = Square()\nshape.old_area(\n    1,  # why\n)\n",
            HEAD + "shape = Square()\nshape.area(\n    1,  # why\n)\n",
        ),
        (HEAD + "Square().old_area().real\n", HEAD + "Square().area().real\n"),
        (
            "import acme.shapes\n\nacme.shapes.Shape.old_area(1)\n",
            "import acme.shapes\n\nacme.shapes.Shape.area(1)\n",
        ),
        (
            "from acme.shapes import Shape\n\nhandler = Shape.to_dict\n",
            "from acme.shapes import Shape\n\nhandler = Shape.as_dict\n",
        ),
    ],
)
def test_the_member_takes_the_new_name_and_nothing_else_changes(source: str, written: str) -> None:
    code, edits = tidy(source)
    assert code == written
    assert {row.status for row in edits} == {"auto"}
    assert {row.rule_id for row in edits} == {"rename-members"}


def test_a_member_the_repository_defines_keeps_its_file_as_it_was() -> None:
    source = (
        HEAD
        + "class Ring(Square):\n    def old_area(self):\n        return 1\n\n\n"
        + "Ring().old_area()\nSquare().old_area()\n"
    )
    code, edits = tidy(source)
    assert (code, edits) == (source, [])
    # A class below `Square` defines the member, so no read of it is the library's any more.
    assert [(row[1], row[2]) for row in acme.statuses(scanned(source))] == [
        ("needs_review", "member_overridden"),
        ("needs_review", "member_overridden"),
    ]


def test_a_file_with_nothing_to_rename_reports_nothing() -> None:
    code, edits = tidy("x = 1\n")
    assert (code, edits) == ("x = 1\n", [])


def test_the_rule_claims_what_it_renames_and_nothing_else() -> None:
    rule = RenameMember(RENAME)
    assert (rule.consumes, rule.client_readers) == (frozenset(), frozenset())
    rows = scanned(HEAD + "Square().old_area()\nShape.to_dict\n").findings
    assert [rule.claims(row) for row in rows] == [True, True]


def test_the_new_name_goes_over_whatever_another_rule_made_of_the_value() -> None:
    """The rename is recorded as a name, so a value another rule replaced is not undone."""
    module = cst.parse_module("shape.old_area()\n")
    context = base.RuleContext.build(ImpactPlan(path="probe.py"), module, SPEC)
    line = cst.ensure_type(module.body[0], cst.SimpleStatementLine)
    call = cst.ensure_type(cst.ensure_type(line.body[0], cst.Expr).value, cst.Call)
    member = cst.ensure_type(call.func, cst.Attribute)
    context.rewrites.rename_member(member, "area")
    context.rewrites.set(member.value, cst.Name("other"))
    assert base.finish(context).code == "other.area()\n"


@pytest.mark.parametrize(
    ("fields", "says"),
    [
        ({"class_symbol": "not a name", "members": ("old",)}, "must be a qualified name"),
        ({"class_symbol": BASE, "members": ()}, "has no member to rename"),
        ({"class_symbol": BASE, "members": ("not-a-name", "old")}, "takes plain names"),
    ],
)
def test_a_member_class_names_a_class_and_the_plain_names_renamed_on_it(
    fields: dict[str, object], says: str
) -> None:
    with pytest.raises(ValueError, match=says):
        MemberClass(**fields)


def test_a_member_the_pack_flags_is_flagged_on_a_receiver_too() -> None:
    source = HEAD + "def check(item: Square):\n    return item.retired\n"
    rows = acme.statuses(scanned(source))
    assert rows == [(9, "needs_review", "flag_only_surface")]


def test_the_flagged_member_is_the_flag_rules_and_not_the_renames() -> None:
    row = scanned(HEAD + "def check(item: Square):\n    return item.retired\n").findings[0]
    assert (row.symbol, RenameMember(RENAME).claims(row)) == (f"{BASE}.retired", False)


@pytest.mark.parametrize(
    ("call", "status"),
    [
        ("item.to_dict(indent=2)", "auto"),
        ("item.to_dict()", "auto"),
        ("item.to_dict(depth=1)", "needs_review"),
        ("item.to_dict(indent=1, depth=1)", "needs_review"),
        ("item.to_dict(*rest)", "needs_review"),
        ("item.to_dict(**rest)", "needs_review"),
        ("item.old_area(depth=1)", "auto"),
    ],
)
def test_a_call_the_new_spelling_takes_fewer_keywords_for_is_refused_when_it_passes_one_it_lacks(
    call: str, status: str
) -> None:
    source = HEAD + f"def check(item: Square, rest):\n    return {call}\n"
    code, edits = tidy(source)
    assert [row.status for row in edits] == [status]
    assert (code == source) is (status == "needs_review")
    if status == "needs_review":
        assert [row.reason for row in edits] == ["unsupported_kwarg"]


def test_a_member_read_that_is_not_a_call_is_renamed_whatever_the_new_spelling_takes() -> None:
    code, edits = tidy(HEAD + "def check(item: Square):\n    return item.to_dict\n")
    assert code.endswith("return item.as_dict\n")
    assert [row.status for row in edits] == ["auto"]


def test_a_takes_entry_names_a_member_and_sorted_keywords() -> None:
    from obelize.packs.schema import RenameMemberParams

    members = {f"{BASE}.to_dict": "as_dict"}
    assert RenameMemberParams(members=members, takes={f"{BASE}.to_dict": ()}).takes
    for takes, says in (
        ({f"{BASE}.other": ("a",)}, "is not a member in members"),
        ({f"{BASE}.to_dict": ("b", "a")}, "must be sorted"),
    ):
        with pytest.raises(ValueError, match=says):
            RenameMemberParams(members=members, takes=takes)


# What a class binds in any statement and in any branch is the class's own, however it is bound.


@pytest.mark.parametrize("body", BINDINGS)
def test_a_member_a_class_binds_by_any_statement_is_the_repositorys_own(body: str) -> None:
    source = HEAD.replace("    pass", f"    {body}") + "\n\nSquare().old_area()\n"
    assert [(row[1], row[2]) for row in acme.statuses(scanned(source))] == [
        ("needs_review", "member_overridden")
    ]


@pytest.mark.parametrize("body", UNBOUND)
def test_what_a_class_does_not_bind_at_its_own_level_is_not_a_member_it_defines(body: str) -> None:
    source = HEAD.replace("    pass", f"    {body}") + "\n\nSquare().old_area()\n"
    assert [(row[1], row[2]) for row in acme.statuses(scanned(source))] == [("eligible", None)]


def test_a_receiver_that_is_a_star_parameter_is_a_tuple_or_a_dict_and_no_shape() -> None:
    source = (
        HEAD
        + "def f(*items: Square, **named: Square):\n    return items.old_area(), named.to_dict\n"
    )
    assert found(source) == []


@pytest.mark.parametrize(
    "case",
    [
        "case [shape, _]:",
        "case Square() as shape:",
        "case {'k': 1, **shape}:",
        "case [*shape]:",
        "case shape:",
    ],
)
def test_a_name_a_match_pattern_binds_is_no_longer_the_shape_it_was(case: str) -> None:
    source = (
        HEAD
        + "shape = Square()\n\n\ndef f(value):\n    match value:\n"
        + f"        {case}\n            return shape.old_area()\n"
    )
    assert found(source) == []


def test_a_pattern_that_binds_nothing_leaves_the_name_typed() -> None:
    source = (
        HEAD
        + "shape = Square()\n\n\ndef f(value):\n    match value:\n"
        + "        case {'k': 1}:\n            return shape.old_area()\n"
        + "        case [*_]:\n            return 0\n        case _:\n            return 1\n"
    )
    assert [row[3] for row in found(source)] == [f"{BASE}.old_area"]


def test_a_subclass_that_defines_the_member_withholds_it_for_the_classes_above_it() -> None:
    source = (
        HEAD
        + "class Ring(Square):\n    def f(self):\n        return self.old_area()\n\n\n"
        + "class Sub(Ring):\n    def old_area(self):\n        return 5\n\n\n"
        + "def g(item: Ring, other: Square):\n    return item.old_area(), other.to_dict\n"
    )
    assert [(row[1], row[2]) for row in acme.statuses(scanned(source))] == [
        ("needs_review", "member_overridden"),
        ("needs_review", "member_overridden"),
        ("eligible", None),
    ]
