"""`configure_to_client` against the fake `acme` pack, so no Gemini spelling can hide in the rule.

Names come from `acme.CLIENT`; the import rule runs too, as the client rule reads the name it bound.
"""

from __future__ import annotations

import acme
import pytest

from obelize.models import Edit
from obelize.packs.schema import Layout

HEADER = "import acme.sdk as sdk\n"


def run(body: str, *, header: str = HEADER, layout: Layout | None = None) -> tuple[str, list[Edit]]:
    return acme.transform(f"{header}\n{body}", acme.CHANGE, acme.CLIENT, layout=layout)


def statuses(edits: list[Edit]) -> list[tuple[int, str, str | None]]:
    return [(row.line, row.status, row.reason) for row in edits]


def test_a_module_level_configure_becomes_a_module_level_client() -> None:
    code, edits = run("sdk.configure(key=KEY)\n")
    assert code == "from acme import client as sdk\n\nhandle = sdk.Client(key=KEY)\n"
    assert statuses(edits) == [(1, "auto", None), (3, "auto", None)]
    assert edits[1].warnings == ("client_constructed_eagerly",)


def test_a_configure_whose_uses_are_all_in_its_own_scope_becomes_a_local() -> None:
    code, edits = run("def go(k):\n    sdk.configure(key=k)\n    return sdk.Model('m').run()\n")
    assert "    handle = sdk.Client(key=k)\n" in code
    assert edits[1].warnings == (), "a local is not constructed when the module is imported"


def test_a_configure_in_a_method_whose_uses_are_elsewhere_becomes_an_attribute() -> None:
    code, _edits = run(
        "class A:\n"
        "    def __init__(self, k):\n"
        "        sdk.configure(key=k)\n"
        "        self.m = sdk.Model('m')\n"
        "\n"
        "    def go(self):\n"
        "        return self.m.run()\n"
    )
    assert "        self.handle = sdk.Client(key=k)\n" in code


def test_the_attribute_is_named_after_the_methods_own_first_parameter() -> None:
    code, _edits = run(
        "class A:\n"
        "    def __init__(this, k):\n"
        "        sdk.configure(key=k)\n"
        "        this.m = sdk.Model('m')\n"
        "\n"
        "    def go(this):\n"
        "        return this.m.run()\n"
    )
    assert "        this.handle = sdk.Client(key=k)\n" in code


def test_a_configure_in_one_function_and_a_use_in_another_is_ambiguous() -> None:
    _code, edits = run(
        "def setup(k):\n    sdk.configure(key=k)\n\n\ndef go():\n    return sdk.Model('m').run()\n"
    )
    assert statuses(edits)[1] == (4, "needs_review", "client_placement_ambiguous")


def test_a_configure_in_a_method_and_a_use_outside_the_class_is_ambiguous() -> None:
    _code, edits = run(
        "class A:\n"
        "    def __init__(self, k):\n"
        "        sdk.configure(key=k)\n"
        "\n"
        "\n"
        "def go():\n"
        "    return sdk.Model('m').run()\n"
    )
    assert statuses(edits)[1] == (5, "needs_review", "client_placement_ambiguous")


def test_a_configure_in_a_method_with_no_parameters_is_ambiguous() -> None:
    """No receiver to hang an attribute on."""
    _code, edits = run(
        "class A:\n"
        "    @staticmethod\n"
        "    def setup():\n"
        "        sdk.configure(key=KEY)\n"
        "\n"
        "    def go(self):\n"
        "        return sdk.Model('m').run()\n"
    )
    assert statuses(edits)[1] == (6, "needs_review", "client_placement_ambiguous")


def test_a_configure_inside_a_function_inside_a_method_is_ambiguous() -> None:
    """The nested scope rebinds the method's receiver name, so an attribute would land elsewhere."""
    _code, edits = run(
        "class A:\n"
        "    def build(self, k):\n"
        "        def inner(self):\n"
        "            sdk.configure(key=k)\n"
        "\n"
        "        return inner\n"
        "\n"
        "    def go(self):\n"
        "        return sdk.Model('m').run()\n"
    )
    assert statuses(edits)[1] == (6, "needs_review", "client_placement_ambiguous")


def test_a_configure_whose_result_is_used_has_nowhere_to_put_the_assignment() -> None:
    _code, edits = run("done = sdk.configure(key=KEY)\n")
    assert statuses(edits)[1] == (3, "needs_review", "client_placement_ambiguous")


def test_two_calls_that_start_in_the_same_column_resolve_to_the_inner_one() -> None:
    """Always the inner call, whatever the metadata order; its parent is a call, hence refused."""
    _code, edits = run("sdk.configure(key=KEY)(1)\n")
    assert statuses(edits)[1] == (3, "needs_review", "client_placement_ambiguous")


@pytest.mark.parametrize(
    ("call", "reason"),
    [
        ("sdk.configure(KEY)", "configure_kwargs_unsupported"),
        ("sdk.configure(**options)", "configure_kwargs_unsupported"),
        ("sdk.configure(*args)", "configure_kwargs_unsupported"),
        ("sdk.configure(key=KEY, transport='rest')", "configure_kwargs_unsupported"),
        ("sdk.configure(credentials={'token': 't'})", "credentials_shape_differs"),
    ],
)
def test_an_argument_the_new_client_cannot_take_refuses_the_row(call: str, reason: str) -> None:
    code, edits = run(f"{call}\n")
    assert statuses(edits)[1] == (3, "needs_review", reason)
    assert call in code, "a refused call is left exactly as it was"


def test_the_allowed_object_keyword_carries_when_it_is_not_a_mapping() -> None:
    code, edits = run("sdk.configure(credentials=CREDENTIALS)\n")
    assert code.endswith("handle = sdk.Client(credentials=CREDENTIALS)\n")
    assert edits[1].warnings == ("client_constructed_eagerly",), "no credential literal, so eager"


def test_both_allowed_keywords_carry_together_in_the_order_they_were_written() -> None:
    code, _edits = run("sdk.configure(key=KEY, credentials=CREDENTIALS)\n")
    assert code.endswith("handle = sdk.Client(key=KEY, credentials=CREDENTIALS)\n")


@pytest.mark.parametrize(
    ("value", "eager"),
    [
        ("'a-key'", False),
        ('"a-key"', False),
        ("''", True),
        ("KEY", True),
        ("f'{PREFIX}-key'", True),
        ("b'a-key'", True),
    ],
)
def test_the_warning_fires_unless_the_credential_is_a_non_empty_string_literal(
    value: str, eager: bool
) -> None:
    """ADR-013 D5's exemption, plus the look-alikes that do not earn it."""
    _code, edits = run(f"sdk.configure(key={value})\n")
    assert bool(edits[1].warnings) is eager


def test_the_credential_keyword_is_the_packs_and_not_a_name_the_rule_knows() -> None:
    _code, literal = run("sdk.configure(key='a-key')\n")
    assert literal[1].warnings == ()
    _code, other = run("sdk.configure(credentials='a-key')\n")
    assert other[1].warnings == ("client_constructed_eagerly",)


def test_a_module_that_binds_the_first_name_gets_the_fallback() -> None:
    code, _edits = run("handle = object()\n\nsdk.configure(key=KEY)\n")
    assert code.endswith("acme_handle = sdk.Client(key=KEY)\n")


def test_a_module_that_binds_both_names_refuses() -> None:
    _code, edits = run("handle = object()\nacme_handle = object()\n\nsdk.configure(key=KEY)\n")
    assert statuses(edits)[1] == (6, "needs_review", "client_name_collision")


def test_a_scope_that_already_reaches_both_names_refuses() -> None:
    """The local placement checks reachability, so module-level names count."""
    _code, edits = run(
        "handle = object()\n"
        "acme_handle = object()\n"
        "\n"
        "\n"
        "def go(k):\n"
        "    sdk.configure(key=k)\n"
        "    return sdk.Model('m').run()\n"
    )
    assert statuses(edits)[1] == (8, "needs_review", "client_name_collision")


def test_a_class_that_already_uses_both_attributes_refuses() -> None:
    _code, edits = run(
        "class A:\n"
        "    def __init__(self, k):\n"
        "        self.handle = None\n"
        "        self.acme_handle = None\n"
        "        sdk.configure(key=k)\n"
        "        self.m = sdk.Model('m')\n"
        "\n"
        "    def go(self):\n"
        "        return self.m.run()\n"
    )
    assert statuses(edits)[1] == (7, "needs_review", "client_name_collision")


def test_an_attribute_the_class_uses_under_another_receiver_is_not_a_collision() -> None:
    code, _edits = run(
        "class A:\n"
        "    def __init__(self, k, other):\n"
        "        other.handle = None\n"
        "        sdk.configure(key=k)\n"
        "        self.m = sdk.Model('m')\n"
        "\n"
        "    def go(self):\n"
        "        return self.m.run()\n"
    )
    assert "        self.handle = sdk.Client(key=k)\n" in code


def line_of(code: str, needle: str) -> str:
    return next(line for line in code.splitlines() if needle in line)


def test_a_call_that_fits_stays_on_one_line_and_one_that_does_not_is_wrapped() -> None:
    """The rewritten line is exactly 74 characters, so it fits at 74 and wraps at 73."""
    body = "sdk.configure(key=environment('SOME_RATHER_LONG_VARIABLE_NAME', ''))\n"
    fits, _edits = run(body, layout=Layout(line_length=74))
    assert line_of(fits, "sdk.Client") == (
        "handle = sdk.Client(key=environment('SOME_RATHER_LONG_VARIABLE_NAME', ''))"
    )
    assert len(line_of(fits, "sdk.Client")) == 74
    wrapped, _edits = run(body, layout=Layout(line_length=73))
    assert wrapped.endswith(
        "handle = sdk.Client(\n    key=environment('SOME_RATHER_LONG_VARIABLE_NAME', ''),\n)\n"
    )


def test_a_trailing_comment_counts_towards_the_width() -> None:
    """The rewritten line plus its comment is 68 characters: fits at 68, wraps at 67."""
    body = "sdk.configure(key=KEY)  # a comment long enough to matter here\n"
    wide, _edits = run(body, layout=Layout(line_length=68))
    assert line_of(wide, "sdk.Client").endswith("# a comment long enough to matter here")
    narrow, _edits = run(body, layout=Layout(line_length=67))
    assert narrow.endswith(
        "handle = sdk.Client(\n    key=KEY,\n)  # a comment long enough to matter here\n"
    )


def test_a_call_the_author_split_is_not_joined_back_up() -> None:
    code, _edits = run("sdk.configure(\n    key=KEY,\n)\n")
    assert code.endswith("handle = sdk.Client(\n    key=KEY,\n)\n")


def test_a_call_split_before_its_argument_wraps_on_the_source_clause_alone() -> None:
    """Isolates the split-source clause: the argument itself renders on one line."""
    code, _edits = run("sdk.configure(\n    key=KEY)\n")
    assert code.endswith("handle = sdk.Client(\n    key=KEY,\n)\n")


def test_a_split_call_is_re_emitted_in_the_canonical_form() -> None:
    code, _edits = run("sdk.configure(key=KEY,\n               credentials=C)\n")
    assert code.endswith("handle = sdk.Client(\n    key=KEY,\n    credentials=C,\n)\n")


def test_an_argument_that_is_itself_multi_line_wraps_the_call_that_holds_it() -> None:
    code, _edits = run("sdk.configure(key=[\n    'a',\n])\n")
    assert code.endswith("handle = sdk.Client(\n    key=[\n    'a',\n],\n)\n")


def test_the_indent_unit_is_the_files_own() -> None:
    body = "def go(k):\n  sdk.configure(\n      key=k,\n  )\n  return sdk.Model('m').run()\n"
    code, _edits = run(body)
    assert "  handle = sdk.Client(\n    key=k,\n  )\n" in code


def test_a_consumed_from_import_becomes_the_module_import_the_client_needs() -> None:
    code, edits = acme.transform(
        "from acme.sdk import configure\n\nconfigure(key=KEY)\n", acme.CHANGE, acme.CLIENT
    )
    assert code == (
        "from acme import client as acme_client\n\nhandle = acme_client.Client(key=KEY)\n"
    )
    assert statuses(edits) == [(1, "auto", None), (3, "auto", None)]


def test_a_file_whose_import_rule_bailed_refuses_with_the_code_it_raised() -> None:
    """Without a bound name for the new module the class cannot be spelled."""
    code, edits = acme.transform(
        "import acme_client\n\nimport acme.sdk\n\nacme.sdk.configure(key=KEY)\n",
        acme.CHANGE,
        acme.CLIENT,
    )
    assert statuses(edits) == [
        (3, "needs_review", "alias_collision"),
        (5, "needs_review", "alias_collision"),
    ]
    assert code == "import acme_client\n\nimport acme.sdk\n\nacme.sdk.configure(key=KEY)\n"


def test_a_rewrite_inside_the_replaced_statement_survives_the_replacement() -> None:
    """A replacement built from the original nodes loses the import rule's `types` swap."""
    code, edits = run("sdk.configure(key=sdk.types.Config)\n")
    assert code == (
        "from acme import client as sdk\n"
        "from acme.client import types\n"
        "\n"
        "handle = sdk.Client(key=types.RunConfig)\n"
    )
    assert [row.status for row in edits] == ["auto", "auto", "auto"]


def test_a_statement_followed_by_another_on_its_line_keeps_its_own_semicolon() -> None:
    """The `Assign` inherits the `Expr`'s end; libcst alone would write a plain `; `."""
    code, edits = run("sdk.configure(key=KEY)  ;  x = 1\n")
    assert code.endswith("handle = sdk.Client(key=KEY)  ;  x = 1\n")
    assert [row.status for row in edits] == ["auto", "auto"]


def test_the_rule_claims_the_configure_call_and_nothing_else() -> None:
    from obelize.transforms.registry import rule_for

    rule = rule_for(acme.CLIENT)
    assert rule is not None
    assert rule.consumes == frozenset({"acme.sdk.configure"})
    result = acme.scan("import acme.sdk as sdk\n\nsdk.configure(key=KEY)\nsdk.Model('m')\n")
    claimed = [finding.line for finding in result.findings if rule.claims(finding)]
    assert claimed == [3]


# The attribute placement uses the first parameter; `cls` or a static method's is not the instance.


@pytest.mark.parametrize(
    "configuring",
    [
        "    @classmethod\n    def setup(cls, k):\n        sdk.configure(key=k)\n",
        "    @staticmethod\n    def setup(k):\n        sdk.configure(key=k)\n",
    ],
    ids=["classmethod", "staticmethod"],
)
def test_a_decorated_configuring_method_is_no_placement(configuring: str) -> None:
    _code, edits = run(
        "class A:\n"
        f"{configuring}"
        "\n"
        "    def __init__(self):\n"
        "        self.m = sdk.Model('m')\n"
        "\n"
        "    def go(self):\n"
        "        return self.m.run()\n"
    )
    assert (6, "needs_review", "client_placement_ambiguous") in statuses(edits)


@pytest.mark.parametrize(
    ("body", "line"),
    [
        ("if True: sdk.configure(key='k')\n\nM = sdk.Model('m')\n", 3),
        (
            "def setup(k):\n    if k:\n        sdk.configure(key=k)\n"
            "    m = sdk.Model('m')\n    return m.run()\n",
            5,
        ),
    ],
    ids=["after-a-colon", "under-an-if-in-a-function"],
)
def test_a_configure_that_may_not_run_is_no_placement(body: str, line: int) -> None:
    _code, edits = run(body)
    assert (line, "needs_review", "client_placement_ambiguous") in statuses(edits)


BASED = (
    "class A{bases}:\n"
    "    def __init__(self, k):\n"
    "        sdk.configure(key=k)\n"
    "        self.m = sdk.Model('m')\n"
    "\n"
    "    def go(self):\n"
    "        return self.m.run()\n"
)


@pytest.mark.parametrize(
    "bases", ["(metaclass=Meta)", "(mod.Base)", "(Later)"], ids=["metaclass", "expression", "below"]
)
def test_a_base_this_rule_cannot_read_takes_both_names(bases: str) -> None:
    """`Later` is defined below, so the class statement read some other `Later`."""
    _code, edits = run(BASED.format(bases=bases) + "\n\nclass Later:\n    pass\n")
    assert (5, "needs_review", "client_name_collision") in statuses(edits)


def test_object_is_a_base_with_nothing_on_it() -> None:
    code, _edits = run(BASED.format(bases="(object)"))
    assert "        self.handle = sdk.Client(key=k)\n" in code


def test_a_decorator_that_keeps_the_receiver_s_name_is_still_no_placement() -> None:
    """A property body runs only when read, so the decorator, not the parameter name, decides."""
    _code, edits = run(
        "class A:\n"
        "    @property\n"
        "    def ready(self):\n"
        "        sdk.configure(key='k')\n"
        "\n"
        "    def __init__(self):\n"
        "        self.m = sdk.Model('m')\n"
        "\n"
        "    def go(self):\n"
        "        return self.m.run()\n"
    )
    assert (6, "needs_review", "client_placement_ambiguous") in statuses(edits)


# A parameter or local called `handle` would capture every rewritten call in its function.


@pytest.mark.parametrize(
    "elsewhere",
    [
        "def go(p, handle=None):\n    return M.run(p)\n",
        "def go(p):\n    handle = object()\n    return M.run(p)\n",
    ],
    ids=["parameter", "local"],
)
def test_a_name_any_scope_binds_is_not_the_module_s_client(elsewhere: str) -> None:
    code, _edits = run("sdk.configure(key='k')\n\nM = sdk.Model('m')\n\n\n" + elsewhere)
    assert "acme_handle = sdk.Client(key='k')\n" in code


def test_both_names_bound_by_other_scopes_is_a_collision() -> None:
    _code, edits = run(
        "sdk.configure(key='k')\n\n\ndef go(handle, acme_handle):\n    return handle\n"
    )
    assert (3, "needs_review", "client_name_collision") in statuses(edits)


def test_a_name_a_nested_scope_binds_is_not_the_local_client() -> None:
    """The comprehension's `handle` is unreachable at `configure` but would capture the call."""
    code, _edits = run(
        "def f(k):\n    sdk.configure(key=k)\n    m = sdk.Model('m')\n"
        "    return [m.run() for handle in range(2)]\n"
    )
    assert "    acme_handle = sdk.Client(key=k)\n" in code
