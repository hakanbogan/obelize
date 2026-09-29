"""`rewrite_call` on the fake `acme` SDK, whose names share nothing with the Gemini pack's.

`acme.LOOKUP` has no configuration class, so a rule reading a shared table instead of its own
parameters would import `acme.MEASURE`'s. The import and client rules run too: calls build on them.
"""

from __future__ import annotations

import acme
import pytest

from obelize.models import Edit
from obelize.packs.schema import Layout

HEADER = "import acme.sdk as sdk\n\nsdk.configure(key='k')\n"


def run(body: str, *, layout: Layout | None = None) -> tuple[str, list[Edit]]:
    return acme.transform(
        f"{HEADER}\n{body}", acme.CHANGE, acme.CLIENT, acme.MEASURE, acme.LOOKUP, layout=layout
    )


def statuses(edits: list[Edit]) -> list[tuple[int, str, str | None]]:
    return [(row.line, row.status, row.reason) for row in edits]


def emitted(body: str) -> str:
    code, edits = run(body)
    assert [row.status for row in edits] == ["auto", "auto", "auto"], statuses(edits)
    return code.splitlines()[-1]


def test_a_call_is_rooted_on_the_client_the_other_rule_placed() -> None:
    code, edits = run("sdk.lookup('kinds/a')\n")
    assert code.splitlines() == [
        "from acme import client as sdk",
        "",
        "handle = sdk.Client(key='k')",
        "",
        "handle.registry.fetch(tag='kinds/a')",
    ]
    assert statuses(edits) == [(1, "auto", None), (3, "auto", None), (5, "auto", None)]


def test_a_positional_argument_is_lifted_onto_the_name_at_its_index() -> None:
    """The new calls are keyword-only."""
    assert emitted("sdk.measure('a', 'b')\n") == "handle.probe.measure(kind='a', text='b')"


def test_a_renamed_keyword_lands_on_the_new_name_and_one_that_is_not_keeps_its_own() -> None:
    assert emitted("sdk.measure(kind='a', body='b')\n") == (
        "handle.probe.measure(kind='a', text='b')"
    )


def test_a_configuration_keyword_travels_inside_the_class_the_pack_names() -> None:
    assert emitted("sdk.measure(kind='a', depth=2)\n") == (
        "handle.probe.measure(kind='a', opts=types.MeasureConfig(depth=2))"
    )


def test_the_configuration_import_arrives_only_when_something_carries_one() -> None:
    assert "import types" not in run("sdk.lookup('kinds/a')\n")[0]
    assert "from acme.client import types" in run("sdk.measure(kind='a', tone='dry')\n")[0]


def test_the_fields_keep_the_order_the_author_wrote_them_in() -> None:
    assert emitted("sdk.measure(tone='dry', kind='a', depth=2)\n") == (
        "handle.probe.measure(kind='a', opts=types.MeasureConfig(tone='dry', depth=2))"
    )


def test_a_call_with_no_arguments_emits_a_call_with_no_arguments() -> None:
    """Not an empty configuration object, though the new class would accept one."""
    assert emitted("sdk.measure()\n") == "handle.probe.measure()"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("sdk.measure(kind='a', retries=3)\n", "unsupported_kwarg"),
        ("sdk.measure(**options)\n", "unsupported_kwarg"),
        ("sdk.measure(*args)\n", "unsupported_kwarg"),
        ("sdk.measure('a', 'b', 'c')\n", "positional_arg_ambiguous"),
        ("sdk.measure('a', kind='b')\n", "positional_arg_ambiguous"),
    ],
)
def test_an_argument_the_pack_cannot_place_refuses_the_call(body: str, reason: str) -> None:
    _code, edits = run(body)
    assert statuses(edits)[-1] == (5, "needs_review", reason)


def test_a_refused_call_leaves_its_own_line_and_nothing_else_alone() -> None:
    """A free call holds no group; ADR-010 F-1 keeps the half-rewritten file off disk a layer up."""
    code, edits = run("sdk.measure(kind='a', retries=3)\n")
    assert code.splitlines()[-1] == "sdk.measure(kind='a', retries=3)"
    assert [row.status for row in edits] == ["auto", "auto", "needs_review"]


def test_a_module_with_no_client_refuses_under_the_planners_own_code() -> None:
    code, edits = acme.transform(
        "import acme.sdk as sdk\n\nsdk.lookup('kinds/a')\n", acme.CHANGE, acme.LOOKUP
    )
    assert statuses(edits) == [(1, "auto", None), (3, "needs_review", "client_source_unresolved")]
    assert code.splitlines()[-1] == "sdk.lookup('kinds/a')"


def test_a_module_whose_client_rule_refused_repeats_that_rules_code() -> None:
    """One defect gets one code. No `HEADER`: a second `configure` is a different defect."""
    _code, edits = acme.transform(
        "import acme.sdk as sdk\n\nsdk.configure(transport='grpc')\nsdk.lookup('kinds/a')\n",
        acme.CHANGE,
        acme.CLIENT,
        acme.LOOKUP,
    )
    assert statuses(edits) == [
        (1, "auto", None),
        (3, "needs_review", "configure_kwargs_unsupported"),
        (4, "needs_review", "configure_kwargs_unsupported"),
    ]


def test_a_finding_the_scan_withheld_is_not_this_rules_to_report() -> None:
    """`alias = sdk` withholds the file (`module_alias_rebound`) before any rule runs."""
    source = (
        "import acme.sdk as sdk\n\nalias = sdk\n\nsdk.configure(key='k')\nsdk.lookup('kinds/a')\n"
    )
    code, edits = acme.transform(source, acme.CHANGE, acme.CLIENT, acme.LOOKUP)
    assert edits == []
    assert code == source


def test_a_module_that_has_taken_both_submodule_names_refuses_the_configuration() -> None:
    code, edits = acme.transform(
        "import acme.sdk as sdk\n\ntypes = {}\nacme_types = {}\n\n"
        "sdk.configure(key='k')\nsdk.measure(kind='a', depth=2)\n",
        acme.CHANGE,
        acme.CLIENT,
        acme.MEASURE,
    )
    assert statuses(edits)[-1] == (7, "needs_review", "alias_collision")
    assert code.splitlines()[-1] == "sdk.measure(kind='a', depth=2)"


def test_a_result_read_the_old_way_refuses_the_call_that_produced_it() -> None:
    _code, edits = run("answer = sdk.measure(kind='a')\nuse(answer['score'])\n")
    assert statuses(edits)[-1] == (5, "needs_review", "response_shape_changed")


def test_the_read_is_seen_on_the_call_itself_as_well_as_through_a_name() -> None:
    _code, edits = run("use(sdk.measure(kind='a')['score'])\n")
    assert statuses(edits)[-1] == (5, "needs_review", "response_shape_changed")


@pytest.mark.parametrize(
    "source",
    [
        "answer = sdk.measure(kind='a')\nuse(answer['other'])\n",
        "answer = sdk.measure(kind='a')\nuse(answer.get('score'))\n",
        "use(sdk.measure(kind='a'))\n",
        "def f():\n    return sdk.measure(kind='a')\n",
        "answer = sdk.measure(kind='a')\n",
    ],
    ids=["another key", "a get", "passed on", "returned", "bound and never read here"],
)
def test_a_result_that_is_used_at_all_refuses_the_call(source: str) -> None:
    """Whatever receives the result expects the legacy shape; a flagged-key read is only one use."""
    _code, edits = run(source)
    assert statuses(edits)[-1][1:] == ("needs_review", "response_shape_changed")


def test_a_result_thrown_away_is_the_one_that_is_written() -> None:
    _code, edits = run("sdk.measure(kind='a')\n")
    assert statuses(edits)[-1] == (5, "auto", None)


@pytest.mark.parametrize(
    "source",
    [
        "for item in sdk.lookup('kinds/a'):\n    use(item.gone)\n",
        "names = [i.name for i in sdk.lookup('kinds/a') if i.gone]\n",
        "answer = sdk.lookup('kinds/a')\nuse(answer.gone)\n",
        "answer = sdk.lookup('kinds/a')\nuse(getattr(answer, 'gone', None))\n",
        "use(getattr(sdk.lookup('kinds/a'), 'gone'))\n",
    ],
    ids=[
        "a loop",
        "a comprehension",
        "a bound name",
        "getattr",
        "getattr of the call",
    ],
)
def test_a_field_the_new_result_lacks_refuses_the_call(source: str) -> None:
    """No `sdk.lookup(...).gone`: the driver withholds that file as `usage_unmapped` first."""
    _code, edits = run(source)
    assert statuses(edits)[-1][1:] == ("needs_review", "attribute_removed")


@pytest.mark.parametrize(
    "source",
    [
        "for item in sdk.lookup('kinds/a'):\n    use(item.name)\n",
        "answer = sdk.lookup('kinds/a')\nuse(getattr(OTHER, 'gone', answer))\n",
        "answer = sdk.lookup('kinds/a')\nuse(getattr(answer, 'name'))\n",
        "answer = sdk.lookup('kinds/a')\nuse(answer, 'gone')\n",
        "def f():\n    answer = sdk.lookup('kinds/a')\n    return answer.name\n\n\n"
        "def g(answer):\n    return answer.gone\n",
        "for a, b in sdk.lookup('kinds/a'):\n    use(a.gone)\n",
        "def f():\n    return sdk.lookup('kinds/a')\n",
    ],
    ids=[
        "another field",
        "handed to getattr as its default",
        "getattr of another field",
        "the field's name handed to another function",
        "the same spelling in another function",
        "a tuple target",
        "returned",
    ],
)
def test_what_the_rule_does_not_follow_is_written(source: str) -> None:
    """The last two are shapes the rule does not follow; `returned` is `COVERAGE.md` gap 22."""
    _code, edits = run(source)
    assert statuses(edits)[-1][1:] == ("auto", None)


@pytest.mark.parametrize(
    ("handled", "status"),
    [
        ("errors.Busy", ("needs_review", "error_class_changed")),
        ("ValueError", ("auto", None)),
    ],
    ids=["a legacy class", "another class"],
)
def test_a_call_a_legacy_handler_catches_is_refused(
    handled: str, status: tuple[str, str | None]
) -> None:
    source = (
        f"from acme import errors\ntry:\n    sdk.measure(kind='a')\nexcept {handled}:\n    pass\n"
    )
    _code, edits = run(source)
    assert statuses(edits)[-1][1:] == status


def test_a_result_the_rule_never_flagged_a_read_for_is_never_looked_at() -> None:
    """`acme.LOOKUP` declares no `result_access_flags`, so nothing is scanned for."""
    _code, edits = run("answer = sdk.lookup('kinds/a')\nuse(answer['score'])\n")
    assert statuses(edits)[-1] == (5, "auto", None)


@pytest.mark.parametrize(
    "body",
    [
        "sdk.lookup('other/a')\n",
        "sdk.lookup(tag)\n",
        "sdk.lookup()\n",
        "sdk.lookup(f'kinds/{name}')\n",
    ],
    ids=["another prefix", "a name", "nothing at all", "an f-string"],
)
def test_a_name_the_rule_cannot_read_is_a_result_it_cannot_promise(body: str) -> None:
    _code, edits = run(body)
    assert statuses(edits)[-1] == (5, "needs_review", "response_shape_changed")


def test_the_call_refuses_its_own_argument_before_it_refuses_its_answer() -> None:
    """The declared order: a code that names the call beats one that names its result."""
    _code, edits = run("sdk.lookup('other/a', 'spare')\n")
    assert statuses(edits)[-1] == (5, "needs_review", "positional_arg_ambiguous")


def test_the_configuration_and_the_call_wrap_at_the_width_the_pack_sets() -> None:
    code, _edits = run(
        "sdk.measure(kind='a', depth=2, tone='dry')\n", layout=Layout(line_length=48)
    )
    assert code.splitlines()[-7:] == [
        "handle.probe.measure(",
        "    kind='a',",
        "    opts=types.MeasureConfig(",
        "        depth=2,",
        "        tone='dry',",
        "    ),",
        ")",
    ]
