"""Escape rule and group bail, plus the code order and line claims the oracle does not pin."""

from __future__ import annotations

from acme import SPEC, scan

from obelize.impact import dataflow
from obelize.models import BAIL_CODES

CONFIGURED = "import acme.sdk as sdk\n\nsdk.configure(key='k')\n\n"


def groups(source: str) -> tuple[dataflow.Group, ...]:
    return dataflow.groups(scan(CONFIGURED + source))


def codes(source: str) -> list[tuple[str, str, int, str | None]]:
    return [
        (group.receiver.kind, group.receiver.name, group.receiver.ctor_line, group.bail)
        for group in groups(source)
    ]


def test_every_code_this_module_raises_has_a_rung_and_is_a_real_bail() -> None:
    assert dataflow.BAILS <= BAIL_CODES
    assert set(dataflow.RUNG) == dataflow.BAILS
    assert set(dataflow.ORDER) == dataflow.BAILS
    assert set(dataflow.RUNG.values()) == {5}, "all three are the binding group, which is rung 5"


def test_a_closed_world_group_withholds_nothing() -> None:
    assert codes("def ask(q):\n    m = sdk.Model('m')\n    return m.run(q)\n") == [
        ("name", "m", 6, None)
    ]


def test_a_constructor_in_the_class_body_withholds_the_group() -> None:
    """ADR-008 D2 supports `self_attr` and leaves `class_attr` out."""
    assert codes(
        "class Asker:\n"
        "    model = sdk.Model('m')\n"
        "\n"
        "    def ask(self, q):\n"
        "        return self.model.run(q)\n"
    ) == [("class_attr", "model", 6, "class_attr_binding")]


def test_a_constructor_in_the_initialiser_does_not() -> None:
    """The same `self.model` reads as the class-body case; only the constructor's site differs."""
    assert codes(
        "class Asker:\n"
        "    def __init__(self):\n"
        "        self.model = sdk.Model('m')\n"
        "\n"
        "    def ask(self, q):\n"
        "        return self.model.run(q)\n"
    ) == [("self_attr", "self.model", 7, None)]


def test_a_name_assigned_twice_withholds_the_group() -> None:
    """Every assignment counts: counting only legacy constructors would miss `other()` here."""
    assert codes(
        "def ask(q, fallback=False):\n"
        "    m = sdk.Model('m')\n"
        "    if fallback:\n"
        "        m = other()\n"
        "    return m.run(q)\n"
    ) == [("name", "m", 6, "multiple_assignments")]


def test_two_constructors_for_one_name_report_the_use_once() -> None:
    """Both groups hold the one `m.run(q)`; analysis dedupes it by node identity."""
    source = (
        "def ask(q, fallback=False):\n"
        "    m = sdk.Model('a')\n"
        "    if fallback:\n"
        "        m = sdk.Model('b')\n"
        "    return m.run(q)\n"
    )
    assert codes(source) == [
        ("name", "m", 6, "multiple_assignments"),
        ("name", "m", 8, "multiple_assignments"),
    ]
    result = scan(CONFIGURED + source)
    assert [(f.line, f.kind, f.symbol) for f in result.findings if f.line == 9] == [
        (9, "method_call", "acme.sdk.Model.run")
    ]


def test_a_reference_that_is_not_a_receiver_withholds_the_group() -> None:
    """Passed as an argument: the object leaves the closed world."""
    assert codes("def ask(q):\n    m = sdk.Model('m')\n    save(m)\n    return m.run(q)\n") == [
        ("name", "m", 6, "model_object_escapes")
    ]


def test_the_constructor_site_outranks_the_escape() -> None:
    """Both fired. `class_attr_binding` says the uses do not matter yet."""
    assert codes(
        "class Asker:\n"
        "    model = sdk.Model('m')\n"
        "\n"
        "    def ask(self, q):\n"
        "        save(self.model)\n"
        "        return self.model.run(q)\n"
    ) == [("class_attr", "model", 6, "class_attr_binding")]


def test_a_second_assignment_outranks_the_escape() -> None:
    """Both fired. Which object escaped is not knowable, so the code says that."""
    assert codes(
        "def ask(q, fallback=False):\n"
        "    m = sdk.Model('m')\n"
        "    if fallback:\n"
        "        m = other()\n"
        "    save(m)\n"
        "    return m.run(q)\n"
    ) == [("name", "m", 6, "multiple_assignments")]


def test_the_order_is_the_declared_one_and_covers_every_code() -> None:
    """A code missing from `ORDER` would be silently unreachable in `refusal`."""
    assert dataflow.ORDER == (
        "class_attr_binding",
        "multiple_assignments",
        "model_object_escapes",
    )


def test_a_group_claims_its_constructor_and_its_uses_and_nothing_else() -> None:
    """Line 6 holds two findings; comparing by line number alone would claim `sdk.VERSION` too."""
    result = scan(
        CONFIGURED
        + "def ask(q):\n    m = sdk.Model(sdk.VERSION)\n    save(m)\n    return m.run(q)\n"
    )
    (group,) = dataflow.groups(result)
    assert group.bail == "model_object_escapes"
    assert group.lines == (6, 7, 8)
    claimed = {(finding.line, finding.symbol): group.holds(finding) for finding in result.findings}
    assert claimed == {
        (3, "acme.sdk.configure"): False,
        (1, "acme.sdk"): False,
        (6, "acme.sdk.Model"): True,
        (6, "acme.sdk.VERSION"): False,
        (8, "acme.sdk.Model.run"): True,
    }


def test_a_group_row_is_the_binding_the_report_prints() -> None:
    """`Group.row` is the only place a `Binding` is built from a `Receiver`."""
    (group,) = groups("def ask(q):\n    m = sdk.Model('m')\n    return m.run(q)\n")
    row = group.row("pkg/mod.py", "multiple_assignments")
    assert (row.path, row.kind, row.name, row.scope, row.ctor_line, row.use_lines) == (
        "pkg/mod.py",
        "name",
        "m",
        "function:ask",
        6,
        (7,),
    )
    assert (row.scan_status, row.bail) == ("needs_review", "multiple_assignments")
    assert group.row("pkg/mod.py", None).scan_status == "eligible"


def test_a_file_with_no_binding_has_no_group() -> None:
    """The constructor result is returned rather than bound to anything."""
    assert dataflow.groups(scan(CONFIGURED + "def build():\n    return sdk.Model('m')\n")) == ()
    assert SPEC.constructor_symbols == ("acme.sdk.Model",)
