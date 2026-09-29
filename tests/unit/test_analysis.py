"""One resolution rule per test, against the invented `acme.sdk` spec in `tests/unit/acme.py`."""

from __future__ import annotations

import libcst as cst
import pytest
from acme import SPEC, rows, scan, statuses

from obelize.impact import planner
from obelize.models import Finding, ReceiverMethods
from obelize.scan import analysis, parse


def test_every_code_this_module_raises_has_a_rung_and_is_a_real_bail() -> None:
    from obelize.models import BAIL_CODES

    assert analysis.BAILS <= BAIL_CODES
    assert set(analysis.RUNG) == set(analysis.BAILS)


def test_a_file_with_no_tree_carries_whatever_the_reader_decided() -> None:
    """A file with no module already has its rows from the reader, so it passes through."""
    read = parse.Read(path="probe.py", status="not_a_candidate", data=b"x = 1\n")
    assert analysis.analyse(read, SPEC) == analysis.Analysis(
        path="probe.py", findings=(), receivers=()
    )

    refused = parse.gates("probe.py", b"def f(:\n")
    assert refused.status == "does_not_parse"
    result = analysis.analyse(refused, SPEC)
    assert result.findings == refused.findings
    assert result.receivers == ()


def test_an_import_inside_a_function_body_is_a_local_import() -> None:
    """The code marks only the statement; its uses resolve, and the planner withholds them."""
    result = scan("def build():\n    import acme.sdk as sdk\n\n    return sdk.Model('m')\n")
    assert rows(result) == [
        (2, "import", "alias_resolved", "acme.sdk"),
        (4, "call", "alias_resolved", "acme.sdk.Model"),
    ]
    assert statuses(result) == [(2, "needs_review", "local_import"), (4, "eligible", None)]


def test_an_import_in_a_class_body_is_a_local_import_too() -> None:
    result = scan("class Asker:\n    import acme.sdk as sdk\n")
    assert statuses(result) == [(2, "needs_review", "local_import")]


def test_an_import_under_a_type_checking_guard_is_not_a_local_import() -> None:
    """libcst scopes it to the module; an `If` read as local would withhold guarded imports."""
    result = scan(
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from acme.sdk import Model\n"
    )
    assert statuses(result) == [(4, "eligible", None)]


def test_a_refused_surface_outranks_where_the_statement_sits() -> None:
    """Rung 1 wins; the `from` import names the module, so only its `protos` read is refused."""
    result = scan("def load():\n    import acme.sdk.protos as p\n\n    return p\n")
    assert statuses(result) == [
        (2, "needs_review", "flag_only_surface"),
        (4, "needs_review", "flag_only_surface"),
    ]
    through_from = scan("def load():\n    from acme.sdk import protos\n\n    return protos\n")
    assert statuses(through_from) == [
        (2, "needs_review", "local_import"),
        (4, "needs_review", "flag_only_surface"),
    ]


def test_a_relative_import_is_never_the_legacy_module() -> None:
    assert scan("from . import config\nfrom .acme import sdk\n").findings == ()


def test_a_star_import_of_another_package_is_not_a_legacy_star_import() -> None:
    result = scan("from os.path import *\n\njoin('a', 'b')\n")
    assert result.findings == ()


def test_a_dotted_import_binds_only_its_first_segment() -> None:
    """`import acme.sdk` binds `acme`, which is what `conditional_binding` looks up."""
    result = scan("import acme.sdk\n\nacme.sdk.configure(key='k')\n")
    assert rows(result) == [
        (1, "import", "direct_import_resolved", "acme.sdk"),
        (3, "call", "direct_import_resolved", "acme.sdk.configure"),
    ]


def test_a_submodule_import_names_the_submodule_it_imports() -> None:
    result = scan("from acme.sdk.types import Config\n\nC = Config\n")
    assert rows(result) == [
        (1, "import", "from_import_resolved", "acme.sdk.types"),
        (3, "attribute", "from_import_resolved", "acme.sdk.types.Config"),
    ]


def test_one_statement_importing_two_legacy_names_is_one_finding() -> None:
    result = scan("from acme.sdk import Model, configure\n")
    assert rows(result) == [(1, "import", "from_import_resolved", "acme.sdk")]


def test_a_second_import_of_the_same_name_is_a_conditional_binding() -> None:
    """Two `ImportAssignment`s for one name; a plain reassignment keeps its own reason."""
    result = scan(
        "try:\n    import acme.sdk as sdk\nexcept ImportError:\n    import acme.client as sdk\n"
    )
    assert rows(result) == [(2, "import", "conditional_binding", "acme.sdk")]
    assert statuses(result) == [(2, "needs_review", "conditional_binding")]


def test_a_dotted_chain_is_reported_once_and_its_arguments_are_still_walked() -> None:
    result = scan("import acme.sdk as sdk\n\nM = sdk.Model('m', config=sdk.protos.Config(1))\n")
    assert rows(result) == [
        (1, "import", "alias_resolved", "acme.sdk"),
        (3, "call", "alias_resolved", "acme.sdk.Model"),
        (3, "call", "alias_resolved", "acme.sdk.protos.Config"),
    ]


def test_a_flagged_symbol_flags_everything_under_it() -> None:
    """Graded by prefix: the pack names the submodule, whose members cannot all be listed."""
    result = scan("import acme.sdk as sdk\n\nS = sdk.protos.Schema()\n")
    assert statuses(result)[-1] == (3, "needs_review", "flag_only_surface")


def test_a_removed_attribute_is_unsupported() -> None:
    """The pack names the attribute, so the refusal is the most specific thing said."""
    result = scan(
        "import acme.sdk as sdk\n"
        "from acme.sdk import Session\n"
        "\n"
        "def audit(session: Session):\n"
        "    return Session.log\n"
    )
    assert (5, "unsupported", "attribute_removed") in statuses(result)


def test_the_module_read_as_a_value_makes_the_whole_file_rebound() -> None:
    """The only surviving trace of `g = sdk` is the right-hand name."""
    result = scan("import acme.sdk as sdk\n\ng = sdk\n\nM = g.Model('m')\n")
    assert rows(result) == [
        (1, "import", "alias_resolved", "acme.sdk"),
        (3, "attribute", "module_alias_rebound", "acme.sdk"),
    ]
    assert statuses(result) == [
        (1, "needs_review", "module_alias_rebound"),
        (3, "needs_review", "module_alias_rebound"),
    ]


def test_a_local_name_alongside_the_import_is_a_rebinding() -> None:
    """Flow-insensitive: the dead-branch assignment still gives the name LOCAL and IMPORT."""
    result = scan("import acme.sdk as sdk\n\nif not True:\n    sdk = None\n\nM = sdk.Model('m')\n")
    assert (6, "call", "module_alias_rebound", "acme.sdk.Model") in rows(result)


def test_a_module_fetched_by_name_is_reported_for_the_legacy_module_only() -> None:
    result = scan(
        "import importlib\n"
        "import sys\n"
        "\n"
        "a = importlib.import_module('acme.sdk')\n"
        "b = importlib.import_module('os')\n"
        "c = __import__('acme.sdk')\n"
        "sys.modules['acme.sdk'] = a\n"
        "sys.modules['os'] = b\n"
    )
    assert rows(result) == [
        (4, "dynamic", "dynamic_access", "acme.sdk"),
        (6, "dynamic", "dynamic_access", "acme.sdk"),
        (7, "dynamic", "dynamic_access", "acme.sdk"),
    ]
    assert {bail for _line, _status, bail in statuses(result)} == {"flag_only_surface"}


def test_getattr_on_a_resolvable_alias_is_the_escape_and_not_a_by_name_access() -> None:
    """The alias resolves, so this is the rebound escape with `kind: dynamic`, not by-name."""
    result = scan(
        "import acme.sdk as sdk\n"
        "import os\n"
        "\n"
        "cls = getattr(sdk, 'Model')\n"
        "sep = getattr(os, 'sep')\n"
        "bare = getattr(sdk)\n"
    )
    assert rows(result) == [
        (1, "import", "alias_resolved", "acme.sdk"),
        (4, "dynamic", "module_alias_rebound", "acme.sdk.Model"),
        (6, "attribute", "module_alias_rebound", "acme.sdk"),
    ]


def test_a_slice_of_sys_modules_is_not_a_key() -> None:
    result = scan("import sys\n\nkept = list(sys.modules)[0:2]\n")
    assert result.findings == ()


def test_a_pack_that_enables_no_shape_reports_no_shape() -> None:
    """Without the patterns the strings fall to the mention sweep: context, not review items."""
    quiet = SPEC.model_copy(update={"flag_only_patterns": ()})
    result = scan(
        "import importlib\n"
        "from unittest import mock\n"
        "\n"
        "a = importlib.import_module('acme.sdk')\n"
        "p = mock.patch('acme.sdk.Model')\n",
        quiet,
    )
    assert rows(result) == [
        (4, "text_mention", "string_or_comment_mention", "acme.sdk"),
        (5, "text_mention", "string_or_comment_mention", "acme.sdk.Model"),
    ]
    assert {status for _line, status, _bail in statuses(result)} == {"not_a_usage"}


def test_a_legacy_path_in_a_call_argument_is_a_patch_target() -> None:
    result = scan(
        "from unittest import mock\n"
        "\n"
        "p = mock.patch('acme.sdk.Model')\n"
        "q = mock.patch('myapp.sdk')\n"
        "r = log('acme sdk is retired')\n"
    )
    assert rows(result) == [(3, "text_mention", "mock_patch_target", "acme.sdk.Model")]
    assert statuses(result) == [(3, "needs_review", "flag_only_surface")]


@pytest.mark.parametrize(
    "argument",
    ["'see acme.sdk for the note'", "'acme.sdk.Model is retired'"],
    ids=["module", "symbol"],
)
def test_a_dotted_string_that_is_not_a_whole_qualified_name_is_not_a_target(
    argument: str,
) -> None:
    """It must be the whole path: `symbol` passes the prefix check, and only this stops it."""
    result = scan(f"m = log({argument})\n")
    assert [(f.kind, f.confidence_reason) for f in result.findings] == [
        ("text_mention", "string_or_comment_mention")
    ]


def test_a_star_candidate_must_be_a_name_the_pack_declares() -> None:
    """Unassigned accesses alone match every unresolved name, so the pack must declare it too."""
    result = scan(
        "from acme.sdk import *\n"
        "import os\n"
        "\n"
        "configure(key=os.environ['K'])\n"
        "M = Model('m')\n"
        "OTHER = helper()\n"
        "REF = Model\n"
    )
    assert rows(result) == [
        (1, "star_import", "star_import", "acme.sdk"),
        (4, "call", "star_import_candidate", "acme.sdk.configure"),
        (5, "call", "star_import_candidate", "acme.sdk.Model"),
        (7, "attribute", "star_import_candidate", "acme.sdk.Model"),
    ]
    assert {bail for _line, _status, bail in statuses(result)} == {"star_import"}


def test_an_annotated_assignment_binds_the_same_way_a_plain_one_does() -> None:
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "M: 'sdk.Model' = sdk.Model('m')\n"
        "\n"
        "def run(p):\n"
        "    return M.run(p)\n"
    )
    assert [(r.kind, r.name, r.scope, r.ctor_line, r.use_lines) for r in result.receivers] == [
        ("module_const", "M", "module", 3, (6,))
    ]
    assert (6, "method_call", "receiver_bound_module_const", "acme.sdk.Model.run") in rows(result)


def test_a_conditional_or_defaulted_constructor_still_binds() -> None:
    """Stopping at the `IfExp` or `or` leaves the uses unresolved, worse than either branch."""
    ternary = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "ON = True\n"
        "M = sdk.Model('m') if ON else None\n"
        "\n"
        "def run(p):\n"
        "    return M.run(p)\n"
    )
    assert [(r.kind, r.ctor_line, r.use_lines) for r in ternary.receivers] == [
        ("module_const", 4, (7,))
    ]
    fallback = scan(
        "import acme.sdk as sdk\n\nM = sdk.Model('m') or None\n\ndef run(p):\n    return M.run(p)\n"
    )
    assert [(r.kind, r.ctor_line, r.use_lines) for r in fallback.receivers] == [
        ("module_const", 3, (6,))
    ]


def test_a_second_assignment_to_the_same_name_is_counted() -> None:
    """Only counted here; withholding the group is `impact/dataflow.py`'s."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "def run(p):\n"
        "    m = sdk.Model('a')\n"
        "    m = sdk.Model('b')\n"
        "    return m.run(p)\n"
    )
    assert [r.assignments for r in result.receivers] == [2, 2]


def test_a_self_attribute_needs_a_constructor_and_not_just_a_name() -> None:
    """Keyed on (ClassDef, first parameter, attribute); the name alone would join `Renderer`."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Wrapper:\n"
        "    def __init__(self):\n"
        "        self.model = sdk.Model('m')\n"
        "\n"
        "    def run(self, p):\n"
        "        return self.model.run(p)\n"
        "\n"
        "class Renderer:\n"
        "    def __init__(self, model):\n"
        "        self.model = model\n"
        "\n"
        "    def render(self, p):\n"
        "        return self.model.format(p)\n"
    )
    assert [(r.kind, r.name, r.scope, r.ctor_line, r.use_lines) for r in result.receivers] == [
        ("self_attr", "self.model", "class:Wrapper", 5, (8,))
    ]


def test_a_method_with_no_parameters_contributes_no_attribute() -> None:
    """Reading `params[0]` unguarded would fail the scan on a parameterless `staticmethod`."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Wrapper:\n"
        "    @staticmethod\n"
        "    def version():\n"
        "        return 1\n"
        "\n"
        "    def __init__(self):\n"
        "        self.model = sdk.Model('m')\n"
        "\n"
        "    def run(self, p):\n"
        "        return self.model.run(p)\n"
    )
    assert [(r.kind, r.ctor_line, r.use_lines) for r in result.receivers] == [
        ("self_attr", 9, (12,))
    ]


def test_a_class_body_binds_a_class_attribute_and_ignores_everything_else() -> None:
    """Kind follows the constructor's site, reason the use's spelling: hence `self_attr` uses."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Classifier:\n"
        "    LABELS = ('a', 'b')\n"
        "    first, second = 1, 2\n"
        "    model = sdk.Model('m')\n"
        "\n"
        "    def run(self, p):\n"
        "        return self.model.run(p)\n"
    )
    assert [(r.kind, r.name, r.scope, r.ctor_line, r.use_lines) for r in result.receivers] == [
        ("class_attr", "model", "class:Classifier", 6, (9,))
    ]
    assert (9, "method_call", "receiver_bound_self_attr", "acme.sdk.Model.run") in rows(result)


def test_a_class_attribute_bound_through_a_subscript_is_not_a_name() -> None:
    """`Binding.name` must be a name; the constructor call is still reported, just not grouped."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Registry:\n"
        "    SLOTS = {}\n"
        "    SLOTS['default'] = sdk.Model('m')\n"
    )
    assert result.receivers == ()
    assert (5, "call", "alias_resolved", "acme.sdk.Model") in rows(result)


def test_a_class_attribute_assigned_twice_is_counted_twice() -> None:
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Wrapper:\n"
        "    def __init__(self):\n"
        "        self.model = sdk.Model('a')\n"
        "        self.model = sdk.Model('b')\n"
        "\n"
        "    def run(self, p):\n"
        "        return self.model.run(p)\n"
    )
    assert [(r.name, r.ctor_line, r.assignments) for r in result.receivers] == [
        ("self.model", 5, 2)
    ]


def test_the_receiver_parameter_does_not_have_to_be_called_self() -> None:
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Wrapper:\n"
        "    def __init__(cls):\n"
        "        cls.model = sdk.Model('m')\n"
        "\n"
        "    def run(cls, p):\n"
        "        return cls.model.run(p)\n"
    )
    assert [(r.kind, r.name, r.use_lines) for r in result.receivers] == [
        ("self_attr", "cls.model", (8,))
    ]


def test_an_annotation_with_no_value_binds_nothing() -> None:
    result = scan("import acme.sdk as sdk\n\nM: 'sdk.Model'\n")
    assert result.receivers == ()


def test_a_comprehension_scope_binds_nothing() -> None:
    """`Binding.scope` cannot name it, and `function:<name>` would lie; unresolved beats wrong."""
    result = scan(
        "import acme.sdk as sdk\n\ndef build(names):\n    return [sdk.Model(n) for n in names]\n"
    )
    assert result.receivers == ()
    assert rows(result) == [
        (1, "import", "alias_resolved", "acme.sdk"),
        (4, "call", "alias_resolved", "acme.sdk.Model"),
    ]


def test_what_a_method_returns_is_a_receiver_in_its_own_right() -> None:
    """`Session` has no constructor; without the pack's `method_returns` its uses bind nothing."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Wrapper:\n"
        "    def __init__(self):\n"
        "        self.model = sdk.Model('m')\n"
        "        self.session = self.model.open()\n"
        "\n"
        "    def ask(self, q):\n"
        "        return self.session.ask(q)\n"
        "\n"
        "    def trail(self):\n"
        "        return self.session.log\n"
    )
    assert [(r.kind, r.name, r.receiver, r.ctor_line, r.use_lines) for r in result.receivers] == [
        ("self_attr", "self.model", "acme.sdk.Model", 5, (6,)),
        ("self_attr", "self.session", "acme.sdk.Session", 6, (9, 12)),
    ]
    assert (9, "method_call", "receiver_bound_self_attr", "acme.sdk.Session.ask") in rows(result)
    assert (12, "unsupported", "attribute_removed") in statuses(result)


def test_a_comparison_is_not_an_escape_and_everything_else_is() -> None:
    """Comparing to `None` captures nothing; storing, returning, passing, a non-method read do."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "M = sdk.Model('m')\n"
        "REGISTRY = {'default': M}\n"
        "\n"
        "def get():\n"
        "    return M\n"
        "\n"
        "def name():\n"
        "    return M.title\n"
        "\n"
        "def call(fn):\n"
        "    return fn(M)\n"
        "\n"
        "def ready():\n"
        "    return M is not None\n"
    )
    receiver = result.receivers[0]
    assert receiver.use_lines == (4, 7, 10, 13, 16)
    assert receiver.escape_lines == (4, 7, 10, 13)


def test_a_bound_method_that_is_not_called_is_an_escape() -> None:
    result = scan(
        "import acme.sdk as sdk\n\ndef build():\n    m = sdk.Model('m')\n    return m.run\n"
    )
    assert result.receivers[0].escape_lines == (5,)
    assert (5, "attribute", "receiver_bound_same_scope", "acme.sdk.Model.run") in rows(result)


def test_an_unresolvable_receiver_needs_a_constructor_somewhere_in_the_file() -> None:
    """Gated per file: only a file that builds a legacy object has a symbol to name, not invent."""
    reported = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "def build():\n"
        "    return sdk.Model('m')\n"
        "\n"
        "def run(p):\n"
        "    return build().run(p)\n"
    )
    assert (7, "method_call", "receiver_unresolved", "acme.sdk.Model.run") in rows(reported)
    assert (7, "needs_review", "receiver_unresolved") in statuses(reported)

    silent = scan("from acme import other\n\ndef run(p):\n    return other.build().run(p)\n")
    assert silent.findings == ()


def test_a_method_two_receivers_share_is_named_by_neither() -> None:
    """Reporting the sorted-first owner would put an unmeasured symbol in the evidence."""
    shared = SPEC.model_copy(
        update={
            "supported_methods": (
                ReceiverMethods(receiver="acme.sdk.Model", methods=("ask", "open", "run")),
                ReceiverMethods(receiver="acme.sdk.Session", methods=("ask",)),
            )
        }
    )
    source = (
        "import acme.sdk as sdk\n"
        "\n"
        "def build():\n"
        "    return sdk.Model('m')\n"
        "\n"
        "def go(p):\n"
        "    return build().ask(p)\n"
    )
    assert (7, "method_call", "receiver_unresolved", "acme.sdk.Session.ask") in rows(scan(source))
    assert [
        line
        for line, _kind, reason, _s in rows(scan(source, shared))
        if reason == "receiver_unresolved"
    ] == []


def test_a_resolved_module_function_is_a_call_and_not_an_unresolved_receiver() -> None:
    """A module-level function that shares a method's name resolves on its own."""
    spec = SPEC.model_copy(
        update={
            "symbols": tuple(sorted({*SPEC.symbols, "acme.sdk.run"})),
        }
    )
    result = scan("import acme.sdk as sdk\n\nM = sdk.Model('m')\nout = sdk.run('x')\n", spec)
    assert (4, "call", "alias_resolved", "acme.sdk.run") in rows(result)
    assert [reason for _l, _k, reason, _s in rows(result)] == [
        "alias_resolved",
        "alias_resolved",
        "alias_resolved",
    ]


def test_a_mention_is_anchored_to_the_line_it_occurs_on() -> None:
    result = scan(
        '"""Notes.\n'
        "\n"
        "Two services still import acme.sdk; the tracking issue is\n"
        "https://example.invalid/migrate#acme.sdk.Model and the pin is\n"
        "acme-sdk==1.2.3.\n"
        '"""\n'
    )
    assert rows(result) == [
        (3, "text_mention", "string_or_comment_mention", "acme.sdk"),
        (4, "text_mention", "string_or_comment_mention", "acme.sdk.Model"),
    ]


def test_the_hyphenated_distribution_name_is_never_a_finding() -> None:
    """It trips the byte prefilter, as it should; the analysis is what rejects it."""
    result = scan("# installed from acme-sdk==1.2.3\nPIN = 'acme-sdk>=1'\n")
    assert result.findings == ()


def test_a_line_with_a_finding_carries_no_mention() -> None:
    result = scan("import acme.sdk as sdk  # acme.sdk is retired\n")
    assert rows(result) == [(1, "import", "alias_resolved", "acme.sdk")]


def test_a_mention_in_an_f_string_is_found_and_counted_once() -> None:
    """The whole token is read, and a nested string inside it is not a second row."""
    result = scan("import os\n\nNOTE = f\"{os.sep} acme.sdk {'acme.sdk.Model'}\"\n")
    assert rows(result) == [
        (3, "text_mention", "string_or_comment_mention", "acme.sdk"),
        (3, "text_mention", "string_or_comment_mention", "acme.sdk.Model"),
    ]


def test_a_mention_needs_a_boundary_on_the_left() -> None:
    result = scan("# see myacme.sdk and pkg.acme.sdk, neither of which is ours\n")
    assert result.findings == ()


def test_a_dotted_run_stops_before_a_segment_that_is_not_an_identifier() -> None:
    """`Finding.symbol` is validated as a qualified name, so the regex has to be."""
    result = scan("# acme.sdk.2fast and acme.sdk.Model.\n")
    assert rows(result) == [
        (1, "text_mention", "string_or_comment_mention", "acme.sdk"),
        (1, "text_mention", "string_or_comment_mention", "acme.sdk.Model"),
    ]


def test_a_mention_is_never_stamped_with_the_file_wide_code() -> None:
    """`Finding` rejects `not_a_usage` with a bail, so stamping a mention would crash the scan."""
    result = scan("import acme.sdk as sdk\n\ng = sdk\n# acme.sdk is reached through `g` below\n")
    assert (4, "not_a_usage", None) in statuses(result)
    with pytest.raises(ValueError, match="not_a_usage"):
        Finding(
            path="probe.py",
            line=4,
            column=0,
            kind="text_mention",
            confidence_reason="string_or_comment_mention",
            symbol="acme.sdk",
            scan_status="not_a_usage",
            bail="module_alias_rebound",
        )


def test_the_gate_outranks_a_resolution_defect_and_a_pack_refusal_outranks_both() -> None:
    """All three on one file: the refusal is most specific and survives; the rest take the gate."""
    source = b"import acme.sdk as sdk\rg = sdk\rS = sdk.protos.Schema()\r"
    read = parse.gates("probe.py", source)
    assert read.bail == "roundtrip_mismatch"
    result = analysis.analyse(read, SPEC)
    assert statuses(result) == [
        (1, "needs_review", "roundtrip_mismatch"),
        (2, "needs_review", "roundtrip_mismatch"),
        (3, "needs_review", "flag_only_surface"),
    ]


def test_a_star_import_outranks_a_rebound_alias() -> None:
    """Under a star import nothing resolves at all, so it is the worse defect."""
    result = scan("from acme.sdk import *\nimport acme.sdk as sdk\n\ng = sdk\nM = Model('m')\n")
    assert {bail for _line, _status, bail in statuses(result)} == {"star_import"}


def test_a_clean_file_is_eligible_and_names_no_code() -> None:
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "sdk.configure(key='k')\n"
        "M = sdk.Model('m')\n"
        "\n"
        "def run(p):\n"
        "    return M.run(p)\n"
    )
    assert {(status, bail) for _line, status, bail in statuses(result)} == {("eligible", None)}


def test_findings_come_out_in_document_order() -> None:
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "sdk.configure(key='k')\n"
        "M = sdk.Model('m', config=sdk.protos.Config(1))\n"
        "\n"
        "def run(p):\n"
        "    return M.run(p)\n"
    )
    assert [f.sort_key for f in result.findings] == sorted(f.sort_key for f in result.findings)


def test_the_metadata_wrapper_does_not_copy_the_module() -> None:
    """By default the wrapper deep-copies: every lookup misses silently and the file looks empty."""
    module = cst.parse_module("import acme.sdk as sdk\n")
    from libcst.metadata import MetadataWrapper

    assert MetadataWrapper(module, unsafe_skip_copy=True).module is module
    assert MetadataWrapper(module).module is not module


def test_an_attribute_other_methods_reassign_is_assigned_as_often_as_it_is_written() -> None:
    """`multiple_assignments` counts every write to the attribute, not only legacy constructors."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Wrapper:\n"
        "    def __init__(self):\n"
        "        self.model = sdk.Model('m')\n"
        "\n"
        "    def run(self, p):\n"
        "        return self.model.run(p)\n"
        "\n"
        "    def switch(self, other):\n"
        "        self.model = other\n"
        "\n"
        "    def close(self):\n"
        "        self.model = None\n"
    )
    assert [(r.name, r.assignments, r.escape_lines) for r in result.receivers] == [
        ("self.model", 3, ())
    ]


@pytest.mark.parametrize(
    "export", ["__all__ = ['M', 'run']\n", "__all__ = ('run',)\n__all__ += ('M',)\n"]
)
def test_a_module_constant_another_module_is_told_it_may_import_escapes(export: str) -> None:
    """`__all__` exports the name: an escape, not a use, as nothing on that line is rewritten."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        f"{export}"
        "\n"
        "M = sdk.Model('m')\n"
        "\n"
        "def run(p):\n"
        "    return M.run(p)\n"
    )
    receiver = result.receivers[0]
    exported = 3 + export.count("\n") - 1
    assert receiver.escape_lines == (exported,)
    assert receiver.use_lines == (exported + 5,)


def test_the_attribute_read_through_any_other_receiver_escapes() -> None:
    """Another parameter, a subclass's `self` and a module-level instance all reach it."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Wrapper:\n"
        "    def __init__(self):\n"
        "        self.model = sdk.Model('m')\n"
        "\n"
        "    def run(self, p):\n"
        "        return self.model.run(p)\n"
        "\n"
        "    def same(self, other):\n"
        "        return other.model is self.model\n"
        "\n"
        "class Special(Wrapper):\n"
        "    def reset(self):\n"
        "        self.model = None\n"
        "\n"
        "WRAPPER = Wrapper()\n"
        "NAME = WRAPPER.model.name\n"
    )
    receiver = result.receivers[0]
    assert receiver.escape_lines == (11, 15, 18)
    assert receiver.use_lines == (8, 11)


def test_an_unrelated_class_s_attribute_of_the_same_name_is_not_this_one() -> None:
    """A class that is not a subclass owns its `self.model`; its instances are not this group's."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Wrapper:\n"
        "    def __init__(self):\n"
        "        self.model = sdk.Model('m')\n"
        "\n"
        "    def run(self, p):\n"
        "        return self.model.run(p)\n"
        "\n"
        "class Renderer:\n"
        "    def __init__(self, model):\n"
        "        self.model = model\n"
        "\n"
        "    def render(self, p):\n"
        "        return self.model.format(p)\n"
    )
    assert [(r.name, r.escape_lines, r.assignments) for r in result.receivers] == [
        ("self.model", (), 1)
    ]


def test_the_name_in_any_other_string_or_list_is_not_an_export() -> None:
    """Only `__all__` says another module may import a name."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "NAMES = ['M']\n"
        "print('M', ['M'])\n"
        "\n"
        "M = sdk.Model('m')\n"
        "\n"
        "def run(p):\n"
        "    return M.run(p)\n"
    )
    assert result.receivers[0].escape_lines == ()


def test_a_function_s_own_name_is_not_what_all_lists() -> None:
    """`__all__` names the module's globals, and a local of the same spelling is not one."""
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "__all__ = ['m']\n"
        "\n"
        "def run(p):\n"
        "    m = sdk.Model('m')\n"
        "    return m.run(p)\n"
    )
    assert result.receivers[0].escape_lines == ()


def test_a_class_attribute_is_assigned_where_the_class_body_assigns_it() -> None:
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Wrapper:\n"
        "    model = sdk.Model('m')\n"
        "\n"
        "    def run(self, p):\n"
        "        return self.model.run(p)\n"
    )
    assert [(r.kind, r.assignments) for r in result.receivers] == [("class_attr", 1)]


def test_a_subclass_of_a_subclass_is_the_family_too() -> None:
    result = scan(
        "import acme.sdk as sdk\n"
        "\n"
        "class Wrapper:\n"
        "    def __init__(self):\n"
        "        self.model = sdk.Model('m')\n"
        "\n"
        "    def run(self, p):\n"
        "        return self.model.run(p)\n"
        "\n"
        "class Special(Wrapper):\n"
        "    pass\n"
        "\n"
        "class Later(Special):\n"
        "    def reset(self):\n"
        "        self.model = None\n"
    )
    assert result.receivers[0].escape_lines == (15,)


def test_a_model_named_outside_ascii_is_a_binding_and_not_a_crash() -> None:
    plan = planner.plan(
        scan("import acme.sdk as sdk\n\nmodèle = sdk.Model('m')\nmodèle.run('t')\n"), SPEC
    )
    assert [(row.kind, row.name) for row in plan.bindings] == [("module_const", "modèle")]


def test_an_attribute_named_outside_ascii_is_a_finding_and_not_a_crash() -> None:
    result = scan("import acme.sdk as sdk\n\nprobe = sdk.módel\n")
    assert "acme.sdk.módel" in [row.symbol for row in result.findings]
