"""The module's client, the ladder and atomicity, one rule at a time."""

from __future__ import annotations

from acme import SPEC, scan

from obelize.impact import dataflow, planner
from obelize.models import ATOMICITY_BAIL, BAIL_CODES, Finding, ImpactPlan, ImpactPolicy
from obelize.scan import analysis, parse

DUAL = ImpactPolicy(import_policy="dual")


def plan(source: str, policy: ImpactPolicy | None = None) -> ImpactPlan:
    return planner.plan(scan(source), SPEC, policy)


def graded(source: str, policy: ImpactPolicy | None = None) -> list[tuple[int, str, str | None]]:
    return [
        (finding.line, finding.scan_status, finding.bail)
        for finding in plan(source, policy).findings
    ]


def bindings(source: str) -> list[tuple[str, int, str, str | None]]:
    return [(row.name, row.ctor_line, row.scan_status, row.bail) for row in plan(source).bindings]


def test_the_ladder_is_one_list_and_agrees_with_every_module_that_raises_a_code() -> None:
    """`ORDER` is the whole ladder, and every module's `RUNG` must agree with it."""
    assert set(planner.ORDER) == set(planner.LADDER)
    assert set(planner.ORDER) <= BAIL_CODES
    rungs = [planner.LADDER[code] for code in planner.ORDER]
    assert rungs == sorted(rungs), "the total order must not cross a rung boundary"
    for module in (analysis, dataflow, planner):
        assert {code: planner.LADDER[code] for code in module.RUNG} == module.RUNG
    assert planner.ORDER[-1] == ATOMICITY_BAIL, "atomicity names no defect, so it goes last"


def test_the_three_implemented_passes_raise_disjoint_sets_of_codes() -> None:
    """A code two modules raise is a code neither of them owns."""
    assert not analysis.BAILS & dataflow.BAILS
    assert not analysis.BAILS & planner.BAILS
    assert not dataflow.BAILS & planner.BAILS
    assert set(planner.RUNG) == planner.BAILS
    assert planner.BAILS <= BAIL_CODES
    assert planner.LADDER[parse.PARSE_BAIL] == 2


def test_the_most_specific_of_nothing_is_nothing() -> None:
    assert planner.more_specific([]) is None
    assert planner.more_specific([None, None]) is None
    assert planner.more_specific([ATOMICITY_BAIL, "attribute_removed"]) == "attribute_removed"
    assert planner.more_specific([None, "receiver_unresolved"]) == "receiver_unresolved"


CLOSED = """import acme.sdk as sdk

sdk.configure(key='k')


def ask(q):
    m = sdk.Model('m')
    return m.run(q)
"""

NO_CLIENT = """import acme.sdk as sdk


def ask(q):
    m = sdk.Model('m')
    return m.run(q)
"""

TWO_CLIENTS = """import acme.sdk as sdk


def prod():
    sdk.configure(key='a')


def staging():
    sdk.configure(key='b')


def ask(q):
    m = sdk.Model('m')
    return m.run(q)
"""


def test_one_configure_anywhere_in_the_module_is_the_client_source() -> None:
    assert graded(CLOSED) == [
        (1, "eligible", None),
        (3, "eligible", None),
        (7, "eligible", None),
        (8, "eligible", None),
    ]
    assert bindings(CLOSED) == [("m", 7, "eligible", None)]


def test_no_configure_withholds_the_module_s_call_rewrites() -> None:
    """The import falls to atomicity, since `client_source_unresolved` is forbidden on an import."""
    assert graded(NO_CLIENT) == [
        (1, "needs_review", ATOMICITY_BAIL),
        (5, "needs_review", "client_source_unresolved"),
        (6, "needs_review", "client_source_unresolved"),
    ]
    assert bindings(NO_CLIENT) == [("m", 5, "needs_review", "client_source_unresolved")]


def test_two_configure_calls_withhold_the_module() -> None:
    assert graded(TWO_CLIENTS) == [
        (1, "needs_review", ATOMICITY_BAIL),
        (5, "needs_review", "multiple_configure_calls"),
        (9, "needs_review", "multiple_configure_calls"),
        (13, "needs_review", "multiple_configure_calls"),
        (14, "needs_review", "multiple_configure_calls"),
    ]


def test_a_configure_named_in_a_patch_string_is_not_a_client_source() -> None:
    """A patch target is a `text_mention`; counting it would invent a client, or a second one."""
    source = """import acme.sdk as sdk
from unittest import mock


@mock.patch('acme.sdk.configure')
def test_ask(configure):
    m = sdk.Model('m')
    return m.run('q')
"""
    assert graded(source) == [
        (1, "needs_review", ATOMICITY_BAIL),
        (5, "needs_review", "flag_only_surface"),
        (7, "needs_review", "client_source_unresolved"),
        (8, "needs_review", "client_source_unresolved"),
    ]


def test_only_a_call_a_constructor_or_a_receiver_read_needs_the_client() -> None:
    """Asserted directly: in a plan rung 1 hides the mention, and this keeps rung 4 off imports."""
    rows = {
        "import": ("import", "alias_resolved", "acme.sdk"),
        "mention": ("text_mention", "mock_patch_target", "acme.sdk.configure"),
        "client": ("call", "alias_resolved", "acme.sdk.configure"),
        "constructor": ("call", "alias_resolved", "acme.sdk.Model"),
        "method": ("method_call", "receiver_bound_same_scope", "acme.sdk.Model.run"),
        "chat method": ("method_call", "receiver_bound_same_scope", "acme.sdk.Session.ask"),
        "removed attribute": ("attribute", "receiver_bound_self_attr", "acme.sdk.Session.log"),
        "plain attribute": ("attribute", "alias_resolved", "acme.sdk.VERSION"),
    }
    answers = {
        label: planner.needs_client(
            Finding(
                path="probe.py",
                line=1,
                column=0,
                kind=kind,
                confidence_reason=reason,
                symbol=symbol,
                scan_status="eligible",
            ),
            SPEC,
        )
        for label, (kind, reason, symbol) in rows.items()
    }
    assert answers == {
        "import": False,
        "mention": False,
        "client": True,
        "constructor": True,
        "method": True,
        "chat method": True,
        "removed attribute": True,
        "plain attribute": False,
    }


def test_a_read_that_needs_no_client_is_not_withheld_by_the_client_rung() -> None:
    """A rename needs no client; without this gate every file that names the SDK hits rung 4."""
    assert graded("import acme.sdk as sdk\n\nVERSION = sdk.VERSION\n") == [
        (1, "eligible", None),
        (3, "eligible", None),
    ]


def test_a_removed_attribute_outranks_the_missing_client() -> None:
    """Rung 1 is never displaced: a removed attribute says more than a missing client."""
    assert graded("import acme.sdk as sdk\n\nLOG = sdk.Session.log\n") == [
        (1, "needs_review", ATOMICITY_BAIL),
        (3, "unsupported", "attribute_removed"),
    ]


TWO_CAUSES = """import acme.sdk as sdk

sdk.configure(key='k')

LOG = sdk.Session.log


def ask(q):
    m = sdk.Model('m')
    save(m)
    return m.run(q)
"""


def test_atomicity_names_every_cause_in_the_file_sorted() -> None:
    """Two unrelated causes, so a first-found or libcst-ordered cause list fails (ADR-012)."""
    causes = {
        finding.line: finding.caused_by
        for finding in plan(TWO_CAUSES).findings
        if finding.bail == ATOMICITY_BAIL
    }
    assert causes == {
        1: ("attribute_removed", "model_object_escapes"),
        3: ("attribute_removed", "model_object_escapes"),
    }


def test_atomicity_lands_on_any_eligible_row_and_not_only_on_the_import() -> None:
    """F-1 leaves the file untouched, so line 3's defect-free `configure` is withheld too."""
    assert graded(TWO_CAUSES) == [
        (1, "needs_review", ATOMICITY_BAIL),
        (3, "needs_review", ATOMICITY_BAIL),
        (5, "unsupported", "attribute_removed"),
        (9, "needs_review", "model_object_escapes"),
        (11, "needs_review", "model_object_escapes"),
    ]


def test_a_prose_mention_is_never_stamped_by_atomicity() -> None:
    """`not_a_usage` names something that is not an edit, so no rung withholds it."""
    source = (
        "import acme.sdk as sdk\n\n"
        "# acme.sdk.Model is what this used to build\n"
        "LOG = sdk.Session.log\n"
    )
    assert graded(source) == [
        (1, "needs_review", ATOMICITY_BAIL),
        (3, "not_a_usage", None),
        (4, "unsupported", "attribute_removed"),
    ]


def test_a_prose_mention_on_a_line_the_group_governs_is_still_not_a_usage() -> None:
    """The comment on the escape line names the group's own method, yet must not take its bail."""
    source = """import acme.sdk as sdk

sdk.configure(key='k')


def ask(q):
    m = sdk.Model('m')
    save(m)  # acme.sdk.Model.run is what this used to call
    return m.run(q)
"""
    assert graded(source) == [
        (1, "needs_review", ATOMICITY_BAIL),
        (3, "needs_review", ATOMICITY_BAIL),
        (7, "needs_review", "model_object_escapes"),
        (8, "not_a_usage", None),
        (9, "needs_review", "model_object_escapes"),
    ]
    (group,) = dataflow.groups(scan(source))
    assert group.lines == (7, 8, 9)


def test_the_dual_policy_withholds_nothing_for_atomicity() -> None:
    """`dual` keeps both imports, so each group stands alone and no row gets the atomicity code."""
    assert graded(TWO_CAUSES, DUAL) == [
        (1, "eligible", None),
        (3, "eligible", None),
        (5, "unsupported", "attribute_removed"),
        (9, "needs_review", "model_object_escapes"),
        (11, "needs_review", "model_object_escapes"),
    ]
    assert plan(TWO_CAUSES, DUAL).import_policy == "dual"


LOCAL = """def build(q):
    import acme.sdk as sdk

    sdk.configure(key='k')
    m = sdk.Model('m')
    return m.run(q)
"""


def test_a_binding_withheld_only_by_atomicity_names_no_code_of_its_own() -> None:
    """`Binding` refuses the atomicity code: the group is writable even though the file is not."""
    assert graded(LOCAL) == [
        (2, "needs_review", "local_import"),
        (4, "needs_review", ATOMICITY_BAIL),
        (5, "needs_review", ATOMICITY_BAIL),
        (6, "needs_review", ATOMICITY_BAIL),
    ]
    assert bindings(LOCAL) == [("m", 5, "eligible", None)]


def test_a_binding_carries_the_code_that_withheld_its_own_lines() -> None:
    """The round-trip gate withholds the binding as well as its lines."""
    read = parse.gates("probe.py", CLOSED.replace("\n", "\r").encode("utf-8"))
    assert read.bail == "roundtrip_mismatch"
    withheld = planner.plan(analysis.analyse(read, SPEC), SPEC)
    assert [(row.name, row.scan_status, row.bail) for row in withheld.bindings] == [
        ("m", "needs_review", "roundtrip_mismatch")
    ]


def test_the_group_outranks_an_unresolvable_receiver_on_a_shared_line() -> None:
    """Two same-symbol calls on one line; `ORDER` prefers the group, which names a real binding."""
    source = """import acme.sdk as sdk

sdk.configure(key='k')


def ask(q):
    m = sdk.Model('m')
    save(m)
    return m.run(q) + other().run(q)
"""
    assert graded(source) == [
        (1, "needs_review", ATOMICITY_BAIL),
        (3, "needs_review", ATOMICITY_BAIL),
        (7, "needs_review", "model_object_escapes"),
        (9, "needs_review", "model_object_escapes"),
        (9, "needs_review", "model_object_escapes"),
    ]
    assert [f.column for f in plan(source).findings if f.line == 9] == [11, 22]


def test_every_row_in_a_plan_names_the_file_the_plan_is_for() -> None:
    built = plan(TWO_CAUSES)
    assert built.path == "probe.py"
    assert {finding.path for finding in built.findings} == {"probe.py"}
    assert {row.path for row in built.bindings} == {"probe.py"}
    assert built.import_policy == "atomic"


def test_a_file_with_nothing_in_it_plans_nothing() -> None:
    read = parse.Read(path="probe.py", status="not_a_candidate", data=b"x = 1\n")
    empty = planner.plan(analysis.analyse(read, SPEC), SPEC)
    assert (empty.findings, empty.bindings) == ((), ())


def test_a_file_that_does_not_parse_keeps_its_one_finding() -> None:
    refused = parse.gates("probe.py", b"def f(:\n")
    built = planner.plan(analysis.analyse(refused, SPEC), SPEC)
    assert [(f.kind, f.scan_status, f.bail) for f in built.findings] == [
        ("parse_error", "unsupported", parse.PARSE_BAIL)
    ]
    assert built.bindings == ()


def test_the_policy_defaults_to_the_atomic_rule() -> None:
    """`plan()` takes no policy in the oracle harness and must not invent one."""
    assert (
        planner.plan(scan(CLOSED), SPEC).import_policy
        == planner.plan(scan(CLOSED), SPEC, ImpactPolicy()).import_policy
        == "atomic"
    )
