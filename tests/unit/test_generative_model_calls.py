"""`generative_model_calls` against the fake `acme` pack: a rule that learned Gemini's names fails.

Invented shapes (code that raises `TypeError`, half a response table) belong here, never in an
answer key (ADR-010 F-4).
"""

from __future__ import annotations

import acme
import pytest

from obelize.models import Edit
from obelize.packs.schema import GenerativeModelCallsChange
from obelize.transforms import registry

SETUP = 'import acme.sdk as sdk\n\nsdk.configure(key="k")\n\n'


def run(body: str, change: GenerativeModelCallsChange | None = None) -> tuple[str, list[Edit]]:
    return acme.transform(SETUP + body, acme.CHANGE, acme.CLIENT, change or acme.MODEL)


def refusals(edits: list[Edit]) -> list[str | None]:
    return [row.reason for row in edits if row.rule_id == "model-calls"]


def test_the_model_name_is_folded_into_every_call_under_the_packs_keyword() -> None:
    produced, edits = run('MODEL = sdk.Model("m")\n\n\ndef a(p):\n    return MODEL.run(p).answer\n')
    assert 'handle.models.run(target="m", body=p)' in produced
    assert "sdk.Model" not in produced
    assert refusals(edits) == [None, None]


def test_a_splat_in_the_constructor_is_refused() -> None:
    """The rule cannot say a keyword carries without naming it."""
    _produced, edits = run(
        'OPTIONS = {"label": "m"}\nMODEL = sdk.Model(**OPTIONS)\n\n\n'
        "def a(p):\n    return MODEL.run(p).answer\n"
    )
    assert refusals(edits) == ["unknown_ctor_kwarg", "unknown_ctor_kwarg"]


def test_more_positional_arguments_than_the_signature_has() -> None:
    """Past the end of `ctor_order` there is no name to map an argument onto."""
    _produced, edits = run(
        'MODEL = sdk.Model("m", None, None, None, None, None, "extra")\n\n\n'
        "def a(p):\n    return MODEL.run(p).answer\n"
    )
    assert refusals(edits) == ["positional_arg_ambiguous", "positional_arg_ambiguous"]


def test_one_parameter_given_by_position_and_by_keyword() -> None:
    """Already a `TypeError` as written, so it is refused rather than resolved."""
    _produced, edits = run(
        'MODEL = sdk.Model("m", label="other")\n\n\ndef a(p):\n    return MODEL.run(p).answer\n'
    )
    assert refusals(edits) == ["positional_arg_ambiguous", "positional_arg_ambiguous"]


def test_a_model_name_that_is_not_a_literal_carries_no_warning() -> None:
    """The prefix warning needs a string literal to read."""
    produced, edits = run(
        'NAME = "acme/m"\nMODEL = sdk.Model(NAME)\n\n\ndef a(p):\n    return MODEL.run(p).answer\n'
    )
    assert "target=NAME" in produced
    assert [row.warnings for row in edits if row.rule_id == "model-calls"] == [(), ()]


def test_the_prefix_the_pack_names_and_not_the_one_the_other_pack_names() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("acme/m")\n\n\ndef a(p):\n    return MODEL.run(p).answer\n'
    )
    assert [row.warnings for row in edits if row.rule_id == "model-calls"] == [
        ("model_name_looks_prefixed",),
        (),
    ]
    _produced, edits = run(
        'MODEL = sdk.Model("models/m")\n\n\ndef a(p):\n    return MODEL.run(p).answer\n'
    )
    assert [row.warnings for row in edits if row.rule_id == "model-calls"] == [(), ()]


def test_the_keyword_that_turns_automatic_calling_on_is_refused_by_name() -> None:
    """`helpers` is this pack's spelling of the automatic-calling keyword, whose default flipped."""
    _produced, edits = run(
        'MODEL = sdk.Model("m", helpers=[len])\n\n\ndef a(p):\n    return MODEL.run(p).answer\n'
    )
    assert refusals(edits) == ["afc_semantics_differ", "afc_semantics_differ"]


def test_a_constructor_parameter_the_pack_places_nowhere() -> None:
    """`cache` is in the signature and in none of the five destinations."""
    _produced, edits = run(
        'MODEL = sdk.Model("m", cache=1)\n\n\ndef a(p):\n    return MODEL.run(p).answer\n'
    )
    assert refusals(edits) == ["unknown_ctor_kwarg", "unknown_ctor_kwarg"]


def test_the_configuration_class_and_its_submodule_spelling_are_both_read() -> None:
    for spelling in ("sdk.Config(heat=1)", "sdk.types.Config(heat=1)"):
        produced, edits = run(
            f"MODEL = sdk.Model('m', settings={spelling})\n\n\n"
            "def a(p):\n    return MODEL.run(p).answer\n"
        )
        assert "options=types.RunConfig(heat=1)" in produced, spelling
        assert refusals(edits)[-1] is None, spelling


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("sdk.Config(1)", "a positional argument has no key"),
        ("sdk.Config(**base)", "a splat has no key either"),
        ("sdk.Config(seed=1)", "a key the pack does not list"),
        ('{"seed": 1}', "the same key, in the form nothing validated"),
        ("{**base}", "a mapping spread into another"),
        ("{KEY: 1}", "a key that is not a literal"),
        ("base", "a name this rule cannot follow"),
        ("[1, 2]", "a shape that is neither"),
        ("dict(heat=1)", "a call that is not the configuration class"),
    ],
)
def test_a_configuration_this_rule_cannot_read(value: str, why: str) -> None:
    _produced, edits = run(
        'KEY = "heat"\nbase = {}\n'
        f"MODEL = sdk.Model('m', settings={value})\n\n\n"
        "def a(p):\n    return MODEL.run(p).answer\n"
    )
    assert refusals(edits) == ["generation_config_not_static"] * len(refusals(edits)), why


def test_a_constructor_field_comes_before_the_configurations_own_keys() -> None:
    """The order is the destinations', not the author's."""
    produced, _edits = run(
        "MODEL = sdk.Model('m', settings={'heat': 1}, preamble='hi')\n\n\n"
        "def a(p):\n    return MODEL.run(p).answer\n"
    )
    assert "options=types.RunConfig(preamble='hi', heat=1)" in produced


def test_a_key_only_the_call_has_is_appended_and_one_it_shares_is_replaced() -> None:
    produced, _edits = run(
        "MODEL = sdk.Model('m', settings={'heat': 1})\n\n\n"
        "def a(p):\n    return MODEL.run(p, settings={'heat': 2, 'limit': 9}).answer\n"
    )
    assert "options=types.RunConfig(heat=2, limit=9)" in produced


def test_a_configuration_with_nothing_in_it_is_not_emitted() -> None:
    produced, _edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    return MODEL.run(p).answer\n'
    )
    assert "options=" not in produced


def test_the_safety_table_is_read_from_both_forms_and_emitted_as_one() -> None:
    for value in (
        "{'rude': 'some'}",
        "[{'kind': 'rude', 'level': 'some'}]",
        "(({'kind': 'rude', 'level': 'some'},))",
    ):
        produced, edits = run(
            f"MODEL = sdk.Model('m', guard={value})\n\n\n"
            "def a(p):\n    return MODEL.run(p).answer\n"
        )
        assert "blocks=[" in produced, value
        assert "types.Guard(kind=types.Rudeness.CATEGORY_RUDE, level=types.Block.BLOCK_SOME)" in (
            produced
        ), value
        assert refusals(edits)[-1] is None, value


def test_an_enum_member_carries_across_under_its_own_name() -> None:
    """`BLOCK_ALWAYS` is a member no legacy string maps to, as `HarmBlockThreshold.OFF` is."""
    produced, edits = run(
        "MODEL = sdk.Model('m', guard={sdk.types.Rudeness.CATEGORY_RUDE: "
        "sdk.types.Block.BLOCK_ALWAYS})\n\n\n"
        "def a(p):\n    return MODEL.run(p).answer\n"
    )
    assert "types.Guard(kind=types.Rudeness.CATEGORY_RUDE, level=types.Block.BLOCK_ALWAYS)" in (
        produced
    )
    assert refusals(edits)[-1] is None


def test_the_safety_tables_are_merged_by_category_and_not_wholesale() -> None:
    produced, _edits = run(
        "MODEL = sdk.Model('m', guard={'rude': 'some'})\n\n\n"
        "def a(p):\n    return MODEL.run(p, guard={'rude': sdk.types.Block.BLOCK_ALWAYS}).answer\n"
    )
    assert produced.count("types.Guard(") == 1
    assert "level=types.Block.BLOCK_ALWAYS" in produced


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("{**base}", "a mapping spread into another has no key"),
        ("{'rude': 'some', **base}", "a spread beside a row this rule can read"),
        ("{KEY: 'some'}", "a key that is not a literal and not a member"),
        ("{'rude': KEY}", "a threshold that is not a literal and not a member"),
        ("{'polite': 'some'}", "a category the table does not hold"),
        ("{'rude': 'never'}", "a threshold the table does not hold"),
        ("{sdk.types.Rudeness.CATEGORY_POLITE: 'some'}", "a member the enum does not declare"),
        ("{sdk.Model.CATEGORY_RUDE: 'some'}", "the right member name on the wrong class"),
        ("[1]", "a list element that is not a mapping"),
        ("[{**base}]", "a spread inside the list form"),
        ("[{'kind': 'rude', 'level': 'some', **base}]", "a spread beside both keys of a row"),
        ("[{KEY: 'rude', 'level': 'some'}]", "a key of the list form that is not a literal"),
        ("[{'kind': 'rude'}]", "half a row"),
        ("[{'kind': 'rude', 'level': 'some', 'why': 1}]", "a row with a key too many"),
        ("base", "a name this rule cannot follow"),
        ("'rude'", "a shape that is neither"),
    ],
)
def test_a_safety_table_this_rule_cannot_read(value: str, why: str) -> None:
    _produced, edits = run(
        'KEY = "rude"\nbase = {}\n'
        f"MODEL = sdk.Model('m', guard={value})\n\n\n"
        "def a(p):\n    return MODEL.run(p).answer\n"
    )
    assert refusals(edits) == ["safety_settings_not_static"] * len(refusals(edits)), why


def test_the_rebuilt_table_comes_after_the_fields_that_are_carried() -> None:
    """Carried before rebuilt, so the author's own spellings stay together."""
    produced, _edits = run(
        "MODEL = sdk.Model('m', guard={'rude': 'some'}, settings={'heat': 1}, preamble='hi')\n\n\n"
        "def a(p):\n    return MODEL.run(p).answer\n"
    )
    assert produced.index("preamble=") < produced.index("heat=") < produced.index("blocks=")


def test_a_table_short_enough_to_fit_is_emitted_on_one_line() -> None:
    """Laid out by the same clause as a call, width included."""
    produced, _edits = run("MODEL = sdk.Model('m', guard={'rude': 'some'})\n\nMODEL.run('p')\n")
    assert "blocks=[types.Guard(" in produced


def test_a_chat_is_created_on_the_client_and_read_on_itself() -> None:
    produced, edits = run(
        "def talk(p):\n    MODEL = sdk.Model('m')\n    s = MODEL.chat()\n    return s.ask(p)\n"
    )
    assert "handle.talks.begin(target='m')" in produced
    assert "s.post(note=p)" in produced
    assert refusals(edits) == [None, None, None]


def test_a_history_is_reshaped_and_the_edit_says_so() -> None:
    produced, edits = run(
        "def talk(p):\n    MODEL = sdk.Model('m')\n"
        "    s = MODEL.chat(past=[{'who': 'us', 'said': ['hi', f'{p}!']}])\n"
        "    return s.ask(p)\n"
    )
    assert "past=[{'who': 'us', 'said': [{'words': 'hi'}, {'words': f'{p}!'}]}]" in produced
    assert [row.warnings for row in edits if row.rule_id == "model-calls"] == [
        (),
        ("history_parts_rewritten",),
        (),
    ]


def test_a_history_already_in_the_new_shape_is_not_reshaped() -> None:
    produced, edits = run(
        "def talk(p):\n    MODEL = sdk.Model('m')\n"
        "    s = MODEL.chat(past=[{'who': 'us', 'said': [{'words': 'hi'}]}])\n"
        "    return s.ask(p)\n"
    )
    assert "[{'words': 'hi'}]" in produced
    assert [row.warnings for row in edits if row.rule_id == "model-calls"] == [(), (), ()]


def test_the_generated_key_is_quoted_the_way_the_key_beside_it_is() -> None:
    produced, _edits = run(
        "def talk(p):\n    MODEL = sdk.Model('m')\n"
        '    s = MODEL.chat(past=[{"who": "us", "said": ["hi"]}])\n'
        "    return s.ask(p)\n"
    )
    assert '{"words": "hi"}' in produced


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("past", "a name this rule cannot follow"),
        ("[turn]", "an element that is not a mapping"),
        ("[{**base}]", "a spread where an entry belongs"),
        ("[{KEY: 'us', 'said': ['hi']}]", "a key that is not a literal"),
        ("[{'who': 'us'}]", "half an entry"),
        ("[{'who': 'they', 'said': ['hi']}]", "a role neither SDK accepts"),
        ("[{'who': 'us', 'said': ['hi'], 'extra': 1}]", "an entry with a key too many"),
        ("[{'who': 'us', 'said': ['hi'], **spread}]", "a spread beside both keys of an entry"),
        ("[{'who': 'us', 'said': 'hi'}]", "parts that are not a list"),
        ("[{'who': 'us', 'said': [turn]}]", "a part that could be an object"),
        ("[{'who': 'us', 'said': [*base]}]", "a starred part"),
        ("[{'who': 'us', 'said': [{'words': 'hi', 'x': 1}]}]", "a mapping part with two keys"),
        ("[{'who': 'us', 'said': [{'x': 'hi'}]}]", "a mapping part under another key"),
    ],
)
def test_a_history_this_rule_cannot_read(value: str, why: str) -> None:
    _produced, edits = run(
        'KEY = "who"\nbase = []\nspread = {}\nturn = {}\npast = []\n'
        "def talk(p):\n    MODEL = sdk.Model('m')\n"
        f"    s = MODEL.chat(past={value})\n"
        "    return s.ask(p)\n"
    )
    assert refusals(edits) == ["history_parts_shape_incompatible"] * len(refusals(edits)), why


def test_a_call_on_the_chat_restates_the_whole_configuration_or_none_of_it() -> None:
    """The new SDK replaces the configuration rather than merging it."""
    produced, _edits = run(
        "def talk(p):\n    MODEL = sdk.Model('m', settings={'heat': 1})\n"
        "    s = MODEL.chat()\n"
        "    return s.ask(p, settings={'limit': 9})\n"
    )
    assert "handle.talks.begin(target='m', options=types.RunConfig(heat=1))" in produced
    assert "s.post(note=p, options=types.RunConfig(heat=1, limit=9))" in produced


def test_a_call_on_the_chat_that_overrides_nothing_carries_nothing() -> None:
    produced, _edits = run(
        "def talk(p):\n    MODEL = sdk.Model('m', settings={'heat': 1})\n"
        "    s = MODEL.chat()\n"
        "    return s.ask(p)\n"
    )
    assert "s.post(note=p)" in produced


def test_a_keyword_this_call_refuses_rather_than_moves() -> None:
    """`auto` is this pack's spelling of a call keyword whose default flipped."""
    _produced, edits = run(
        "def talk(p):\n    MODEL = sdk.Model('m')\n"
        "    s = MODEL.chat(auto=True)\n"
        "    return s.ask(p)\n"
    )
    assert refusals(edits) == ["afc_semantics_differ"] * len(refusals(edits))


def test_a_producing_call_whose_result_is_not_assigned_produces_nothing() -> None:
    """Nothing binds the chat, so there is nothing to follow or refuse."""
    produced, edits = run("MODEL = sdk.Model('m')\n\nMODEL.chat()\n")
    assert "handle.talks.begin(target='m')" in produced
    assert refusals(edits) == [None, None]


def test_a_chat_bound_beside_another_on_one_line_is_not_confused_with_it() -> None:
    produced, _edits = run(
        "MODEL = sdk.Model('m')\n\n\ndef f(p):\n"
        "    s = MODEL.chat(past=[]); t = MODEL.chat(settings={'heat': 1})\n"
        "    return s.ask(p, settings={'limit': 9})\n"
    )
    assert "s.post(note=p, options=types.RunConfig(limit=9))" in produced


def test_a_chat_bound_in_another_function_is_not_confused_with_it() -> None:
    produced, _edits = run(
        "MODEL = sdk.Model('m')\n\n\ndef f(p):\n"
        "    s = MODEL.chat(settings={'heat': 1})\n"
        "    return s.ask(p, settings={'limit': 9})\n\n\n"
        "def g(p):\n    s = MODEL.chat()\n    return s.ask(p, settings={'limit': 9})\n"
    )
    assert "options=types.RunConfig(heat=1, limit=9)" in produced
    assert "s.post(note=p, options=types.RunConfig(limit=9))" in produced


def test_a_chat_inherits_what_its_own_creation_emitted() -> None:
    """A chat merges the constructor's configuration and its own; an override restates both."""
    produced, _edits = run(
        "MODEL = sdk.Model('m', settings={'heat': 1})\n\n\ndef f(p):\n"
        "    s = MODEL.chat(settings={'limit': 9})\n"
        "    return s.ask(p, settings={'heat': 2})\n"
    )
    assert "s.post(note=p, options=types.RunConfig(heat=2, limit=9))" in produced


def test_a_group_the_scan_refused_never_reaches_the_rule() -> None:
    """Atomicity withholds every row of the file, so no group forms."""
    source = (
        "def talk(p, kept):\n"
        "    MODEL = sdk.Model('m')\n"
        "    s = MODEL.chat()\n"
        "    kept.append(s)\n"
        "    return s.ask(p)\n"
    )
    produced, edits = run(source)
    assert refusals(edits) == []
    assert "sdk.Model" in produced


def test_an_await_around_an_async_call_is_left_where_it_is() -> None:
    produced, edits = run(
        "MODEL = sdk.Model('m')\n\n\nasync def a(p):\n    return await MODEL.later(p)\n"
    )
    assert "await handle.wait.models.run(target='m', body=p)" in produced
    assert [row.warnings for row in edits if row.rule_id == "model-calls"] == [(), ()]


def test_an_async_stream_keeps_its_await_and_says_so() -> None:
    produced, edits = run(
        "MODEL = sdk.Model('m')\n\n\nasync def a(p):\n"
        "    async for c in await MODEL.later(p, live=True):\n        yield c\n"
    )
    assert "async for c in await handle.wait.models.run_stream(" in produced
    assert [row.warnings for row in edits if row.rule_id == "model-calls"] == [
        (),
        ("async_stream_await_preserved",),
    ]


def test_an_async_stream_with_no_await_is_refused() -> None:
    _produced, edits = run(
        "MODEL = sdk.Model('m')\n\n\nasync def a(p):\n"
        "    async for c in MODEL.later(p, live=True):\n        yield c\n"
    )
    assert refusals(edits) == ["async_stream_await_missing", "async_stream_await_missing"]


def test_a_method_that_is_not_a_coroutine_is_never_asked_about_its_await() -> None:
    """The advised `await` would break a sync method, so only pack-declared coroutines are asked."""
    produced, edits = run(
        "MODEL = sdk.Model('m')\n\n\ndef a(p):\n"
        "    for c in MODEL.run(p, live=True):\n        yield c\n"
    )
    assert "for c in handle.models.run_stream(target='m', body=p):" in produced
    assert refusals(edits) == [None, None]


def test_an_async_stream_bound_without_an_await_carries_no_warning() -> None:
    produced, edits = run(
        "MODEL = sdk.Model('m')\n\n\nasync def a(p):\n    coro = MODEL.later(p, live=True)\n"
        "    async for part in coro:\n        yield part\n"
    )
    assert "handle.wait.models.run_stream(" in produced
    assert [row.warnings for row in edits if row.rule_id == "model-calls"] == [(), ()]


def test_the_streaming_keyword_the_pack_names_sends_the_call_elsewhere() -> None:
    produced, _edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    for part in MODEL.run(p, live=True):\n'
        "        yield part\n"
    )
    assert "handle.models.run_stream(" in produced
    assert "live=" not in produced


@pytest.mark.parametrize(
    "body",
    [
        "    return MODEL.run(p, live=True)\n",
        "    s = MODEL.run(p, live=True)\n    s.resolve()\n",
        "    s = t = MODEL.run(p, live=True)\n    for part in s:\n        yield part\n",
        "    p.s = MODEL.run(p, live=True)\n    for part in p.s:\n        yield part\n",
        "    s = MODEL.run(p, live=True)\n    for part in s:\n        yield part\n"
        "    s = []\n    for part in s:\n        yield part\n",
    ],
    ids=["returned", "resolved", "two names", "an attribute", "a name bound twice"],
)
def test_a_stream_used_other_than_by_a_loop_refuses_the_group(body: str) -> None:
    """The new call returns a generator, which only a loop reads the old way."""
    _produced, edits = run('MODEL = sdk.Model("m")\n\n\ndef a(p):\n' + body)
    assert set(refusals(edits)) == {"response_shape_changed"}


# A model and one function that asks it; `{}` is the function's body.
ASKED = 'MODEL = sdk.Model("m")\n\n\ndef a(p):\n{}'


@pytest.mark.parametrize(
    "body",
    [
        "    return MODEL.run({'who': 'us', 'said': ['hi']}).answer\n",
        "    turns = [{'who': 'us', 'said': [p]}]\n    return MODEL.run(turns).answer\n",
        "    turns = []\n    turns.append({'who': 'us', 'said': [p]})\n"
        "    return MODEL.run(turns).answer\n",
        "    s = MODEL.chat()\n    return s.ask({'who': 'us', 'said': ['hi']}).answer\n",
        "    s = MODEL.chat()\n"
        "    return s.ask([{'who': 'us', 'said': [{'words': 'hi'}]}]).answer\n",
    ],
    ids=[
        "one turn",
        "a name bound to turns",
        "a name appended to",
        "a chat's turn",
        "a chat's turns",
    ],
)
def test_a_turn_the_rule_does_not_reshape_refuses_the_group(body: str) -> None:
    _produced, edits = run(ASKED.format(body))
    assert set(refusals(edits)) == {"history_parts_shape_incompatible"}


def test_a_list_of_turns_in_the_call_is_reshaped_and_says_so() -> None:
    produced, edits = run(
        ASKED.format("    return MODEL.run([{'who': 'us', 'said': ['hi']}]).answer\n")
    )
    assert "body=[{'who': 'us', 'said': [{'words': 'hi'}]}]" in produced
    assert [row.warnings for row in edits if row.rule_id == "model-calls"][-1] == (
        "history_parts_rewritten",
    )


@pytest.mark.parametrize(
    "body",
    [
        "    return MODEL.run(['hi', p]).answer\n",
        "    turns = ['hi', p]\n    return MODEL.run(turns, settings={'heat': 1}).answer\n",
        "    s = MODEL.chat()\n    return s.ask(['hi', p]).answer\n",
        "    return MODEL.run(copyright).answer\n",
    ],
    ids=["a list of parts", "a name holding parts", "a chat's parts", "a builtin's name"],
)
def test_parts_are_carried_as_they_are(body: str) -> None:
    """Both SDKs take parts; in the second, the call line's mapping is not what fills `turns`."""
    _produced, edits = run(ASKED.format(body))
    assert set(refusals(edits)) == {None}


# The import the handlers name their classes through.
ERRORS = "from acme import errors\n"


@pytest.mark.parametrize(
    "source",
    [
        ERRORS
        + ASKED.format(
            "    try:\n        return MODEL.run(p).answer\n"
            "    except errors.Busy:\n        return None\n"
        ),
        ERRORS
        + ASKED.format(
            "    try:\n        return MODEL.run(p).answer\n"
            "    except (ValueError, errors.Busy):\n        return None\n"
        ),
        "import acme.errors\n"
        + ASKED.format(
            "    try:\n        return MODEL.run(p).answer\n"
            "    except acme.errors.Busy:\n        return None\n"
        ),
        "from acme.errors import Busy\n"
        + ASKED.format(
            "    try:\n        return MODEL.run(p).answer\n    except Busy:\n        return None\n"
        ),
    ],
    ids=["through the module", "in a tuple", "by its whole name", "imported by name"],
)
def test_a_call_a_legacy_handler_catches_refuses_the_group(source: str) -> None:
    _produced, edits = run(source)
    assert set(refusals(edits)) == {"error_class_changed"}


@pytest.mark.parametrize(
    "body",
    [
        "    try:\n        return MODEL.run(p).answer\n"
        "    except ValueError:\n        return None\n",
        "    try:\n        return MODEL.run(p).answer\n    except:\n        return None\n",
        "    try:\n        pass\n    except errors.Busy:\n        return MODEL.run(p).answer\n",
        "    try:\n        pass\n    except errors.Busy:\n        return None\n"
        "    else:\n        return MODEL.run(p).answer\n",
        "    try:\n        def inner():\n            return MODEL.run(p).answer\n"
        "    except errors.Busy:\n        return None\n    return inner()\n",
        "    try:\n        return MODEL.run(p).answer\n"
        "    except errors_extra.Busy:\n        return None\n",
    ],
    ids=[
        "another exception",
        "a bare except",
        "in the handler",
        "in the else",
        "in a def it holds",
        "a module that shares the prefix",
    ],
)
def test_a_call_no_legacy_handler_catches_is_written(body: str) -> None:
    """Handlers catch only what their `try` body runs directly, then and there."""
    _produced, edits = run(ERRORS + "from acme import errors_extra\n" + ASKED.format(body))
    assert set(refusals(edits)) == {None}


def test_the_streaming_keyword_written_out_as_false_only_goes_away() -> None:
    produced, _edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    return MODEL.run(p, live=False)\n'
    )
    assert "handle.models.run(" in produced
    assert "live=" not in produced


def test_a_streaming_flag_that_is_not_a_literal() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p, on):\n    return MODEL.run(p, live=on)\n'
    )
    assert refusals(edits) == ["dynamic_stream_flag", "dynamic_stream_flag"]


def test_a_method_with_no_streaming_form_refuses_the_keyword() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    return MODEL.count(p, live=True)\n'
    )
    assert refusals(edits) == ["unsupported_kwarg", "unsupported_kwarg"]


def test_a_splat_in_a_call_is_refused() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p, rest):\n    return MODEL.run(p, **rest)\n'
    )
    assert refusals(edits) == ["unsupported_kwarg", "unsupported_kwarg"]


def test_more_call_positionals_than_the_method_lifts() -> None:
    _produced, edits = run('MODEL = sdk.Model("m")\n\n\ndef a(p, q):\n    return MODEL.run(p, q)\n')
    assert refusals(edits) == ["positional_arg_ambiguous", "positional_arg_ambiguous"]


def test_one_call_argument_given_twice() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p, q):\n    return MODEL.run(p, body=q)\n'
    )
    assert refusals(edits) == ["positional_arg_ambiguous", "positional_arg_ambiguous"]


def test_a_call_keyword_the_new_method_does_not_have() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    return MODEL.run(p, retries=3)\n'
    )
    assert refusals(edits) == ["unsupported_kwarg", "unsupported_kwarg"]


def test_a_method_the_pack_declares_and_gives_no_rewrite() -> None:
    """The whole group, including the chat `open` returns: three rows under one reason."""
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    return MODEL.run(p).answer\n\n\n'
        "def b(p):\n    chat = MODEL.open()\n    return chat.ask(p)\n"
    )
    assert refusals(edits) == [
        "receiver_method_unmapped",
        "receiver_method_unmapped",
        "receiver_method_unmapped",
    ]


def test_the_configuration_a_call_cannot_carry_is_dropped_with_a_warning() -> None:
    produced, edits = run(
        "MODEL = sdk.Model('m', settings={'heat': 1})\n\n\n"
        "def a(p):\n    return MODEL.count(p).total\n"
    )
    assert "options=" not in produced
    assert [row.warnings for row in edits if row.rule_id == "model-calls"] == [
        (),
        ("count_tokens_config_dropped",),
    ]


def test_a_constructor_setting_that_changes_the_answer_is_not_dropped() -> None:
    _produced, edits = run(
        "MODEL = sdk.Model('m', preamble='hi')\n\n\ndef a(p):\n    return MODEL.count(p).total\n"
    )
    assert refusals(edits) == [
        "count_tokens_config_carries_semantics",
        "count_tokens_config_carries_semantics",
    ]


def test_a_group_takes_only_the_calls_made_on_its_own_receiver() -> None:
    produced, edits = run(
        'A = sdk.Model("a")\nB = sdk.Model("b")\n\n\n'
        "def pair(p):\n    return A.run(p).answer, B.run(p).answer\n"
    )
    assert produced.count('target="a"') == 1
    assert produced.count('target="b"') == 1
    assert refusals(edits) == [None, None, None, None]


def test_a_method_with_no_rewrite_stops_its_own_group_and_no_other() -> None:
    """Both receivers are spelled `model`; the lines each binding serves tell the groups apart."""
    _produced, edits = run(
        "def one(p):\n    model = sdk.Model('a')\n    return model.run(p).answer\n\n\n"
        "def two(p):\n    model = sdk.Model('b')\n    s = model.open()\n    return s.ask(p)\n"
    )
    assert refusals(edits) == [None, None, "receiver_method_unmapped", "receiver_method_unmapped"]


def test_a_method_with_no_rewrite_on_a_line_another_group_also_uses() -> None:
    _produced, edits = run(
        'A = sdk.Model("a")\nB = sdk.Model("b")\n\n\n'
        "def both(p):\n    s = B.open(); return A.run(p).answer\n"
    )
    assert refusals(edits) == [None, "receiver_method_unmapped", None]


def test_two_models_that_both_need_the_configuration_import_get_one() -> None:
    """The manager reserves the name it hands back, so the second ask reuses it."""
    produced, _edits = run(
        "A = sdk.Model('a', settings={'heat': 1})\nB = sdk.Model('b', settings={'heat': 2})\n\n\n"
        "def pair(p):\n    return A.run(p).answer, B.run(p).answer\n"
    )
    assert produced.count("from acme.client import types") == 1


def test_an_argument_moved_into_the_new_call_keeps_another_rules_rewrite() -> None:
    """The replacement reuses the author's nodes, so it must be visited to keep their rename."""
    produced, _edits = run(
        "MODEL = sdk.Model('m', settings={'heat': sdk.types.Level.HIGH})\n\n\n"
        "def a(p):\n    return MODEL.run(p).answer\n"
    )
    assert "heat=types.Level.HIGH" in produced
    assert "sdk.types" not in produced


def test_the_semicolon_of_what_is_left_on_the_line_goes() -> None:
    """A semicolon belongs to the statement after it, and that one is gone."""
    produced, _edits = run(
        'LABEL = "m"; MODEL = sdk.Model("m")\n\n\n'
        "def a(p):\n    return MODEL.run(p).answer, LABEL\n"
    )
    assert 'LABEL = "m"\n' in produced
    assert ";" not in produced


def test_the_answer_read_through_a_name_inside_a_handler_that_names_the_error() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    r = MODEL.run(p)\n'
        "    try:\n        return r.answer\n    except LookupError:\n        return None\n"
    )
    assert refusals(edits) == ["response_shape_changed", "response_shape_changed"]


def test_the_answer_read_in_place_inside_the_handler() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n'
        "    try:\n        return MODEL.run(p).answer\n"
        "    except LookupError:\n        return None\n"
    )
    assert refusals(edits) == ["response_shape_changed", "response_shape_changed"]


def test_a_handler_that_names_the_error_among_others() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    r = MODEL.run(p)\n'
        "    try:\n        return r.answer\n    except (TypeError, LookupError):\n"
        "        return None\n"
    )
    assert refusals(edits) == ["response_shape_changed", "response_shape_changed"]


def test_a_handler_that_names_another_error_is_not_this_shape() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    r = MODEL.run(p)\n'
        "    try:\n        return r.answer\n    except TypeError:\n        return None\n"
    )
    assert refusals(edits) == [None, None]


def test_a_bare_handler_is_not_evidence_that_anybody_relied_on_the_error() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    r = MODEL.run(p)\n'
        "    try:\n        return r.answer\n    except:\n        return None\n"
    )
    assert refusals(edits) == [None, None]


def test_a_handler_around_something_that_is_not_this_groups_answer() -> None:
    """The attribute is the right one and the object it is read on is not."""
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p, other):\n    r = MODEL.run(p)\n'
        "    try:\n        return other.answer\n    except LookupError:\n        return r\n"
    )
    assert refusals(edits) == [None, None]


def test_another_attribute_of_the_answer_is_not_this_shape() -> None:
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    r = MODEL.run(p)\n'
        "    try:\n        return r.other\n    except LookupError:\n        return None\n"
    )
    assert refusals(edits) == [None, None]


def test_a_pack_that_names_no_response_attribute_asks_nothing_about_the_answer() -> None:
    """The table is optional, so a pack without one must not be read as empty."""
    quiet = acme.MODEL.model_copy(
        update={
            "params": acme.MODEL.params.model_copy(
                update={"response_attrs_now_none": (), "response_legacy_error": None}
            )
        }
    )
    _produced, edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    r = MODEL.run(p)\n'
        "    try:\n        return r.answer\n    except LookupError:\n        return None\n",
        quiet,
    )
    assert refusals(edits) == [None, None]


def test_a_constructor_inside_a_one_line_block_is_still_deleted() -> None:
    """Left in place it names a renamed module, while every use is rewritten and reported `auto`."""
    produced, edits = run(
        'if True: MODEL = sdk.Model("m")\n\n\ndef a(p):\n    return MODEL.run(p).answer\n'
    )
    assert "sdk.Model" not in produced
    assert "if True: pass" in produced
    assert refusals(edits) == [None, None]


def test_a_one_line_block_with_nothing_of_this_rules_in_it_is_left_alone() -> None:
    produced, _edits = run(
        'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    if not p: return None\n'
        "    return MODEL.run(p).answer\n"
    )
    assert "if not p: return None" in produced


def test_a_constructor_beside_another_statement_in_a_one_line_block() -> None:
    produced, _edits = run(
        'if True: MODEL = sdk.Model("m"); LABEL = "m"\n\n\n'
        "def a(p):\n    return MODEL.run(p).answer, LABEL\n"
    )
    assert 'if True: LABEL = "m"' in produced


def test_a_constructor_whose_result_nobody_keeps() -> None:
    _produced, edits = run('def warm():\n    sdk.Model("m")\n')
    assert refusals(edits) == ["receiver_unresolved"]


def test_without_the_client_rule_there_is_no_client_and_no_reason() -> None:
    """The fallback: a module with a client source and no rule that placed one."""
    _produced, edits = acme.transform(
        SETUP + 'MODEL = sdk.Model("m")\n\n\ndef a(p):\n    return MODEL.run(p).answer\n',
        acme.CHANGE,
        acme.MODEL,
    )
    assert refusals(edits) == ["client_source_unresolved", "client_source_unresolved"]


def test_the_rule_consumes_the_two_names_whose_import_can_go() -> None:
    """A method is reached through an object, so no import statement binds one."""
    built = registry.rule_for(acme.MODEL)
    assert built is not None
    assert built.consumes == frozenset({"acme.sdk.Model", "acme.sdk.Config"})


# Deleting the constructor needs every reference to be a rewritten use; a comparison is no escape
# to the scan (ADR-019 D9) but is still a reference.


def test_a_comparison_on_a_line_of_its_own_refuses_the_group() -> None:
    _produced, edits = run(
        "MODEL = sdk.Model('m')\n\n\n"
        "def a(p):\n    if MODEL is None:\n        return ''\n    return MODEL.run(p).answer\n"
    )
    assert refusals(edits) == ["model_object_escapes", "model_object_escapes"]


def test_a_comparison_on_the_line_of_a_use_refuses_the_group() -> None:
    """The line carries a use, so the rule counts: two references, one use."""
    _produced, edits = run(
        "MODEL = sdk.Model('m')\n\n\n"
        "def a(p):\n    return MODEL.run(p).answer if MODEL is not None else ''\n"
    )
    assert refusals(edits) == ["model_object_escapes", "model_object_escapes"]


def test_a_use_through_another_first_parameter_is_not_one_this_rule_writes() -> None:
    """The scan reads `this.model` as `self.model`, but it is not this rule's receiver."""
    _produced, edits = run(
        "class Desk:\n    def __init__(self):\n        self.model = sdk.Model('m')\n\n"
        "    def ask(this, p):\n        return this.model.run(p).answer\n"
    )
    assert refusals(edits) == ["model_object_escapes", "receiver_unresolved"]


def test_two_uses_on_one_line_are_two_references_and_two_uses() -> None:
    """The control: the count is per use, not one per line."""
    produced, edits = run(
        "MODEL = sdk.Model('m')\n\n\n"
        "def a(p, q):\n    return MODEL.run(p).answer + MODEL.run(q).answer\n"
    )
    assert refusals(edits) == [None, None, None]
    assert "sdk.Model" not in produced


def test_a_chat_used_on_its_model_s_line_is_the_chat_s_use_and_not_the_model_s() -> None:
    _produced, edits = run(
        "def talk(p):\n    MODEL = sdk.Model('m')\n    s = MODEL.chat(); return s.ask(p)\n"
    )
    assert refusals(edits) == [None, None, None]


def test_another_object_s_attribute_of_the_same_name_is_not_a_reference() -> None:
    _produced, edits = run(
        "MODEL = sdk.Model('m')\n\n\n"
        "def a(p, config):\n    return MODEL.run(p).answer + config.MODEL\n"
    )
    assert refusals(edits) == [None, None]


def test_a_parameter_called_types_does_not_capture_the_configuration() -> None:
    """The parameter would shadow the `types` import this rule adds, hence `acme_types`."""
    produced, _edits = run(
        "MODEL = sdk.Model('m', settings={'heat': 1})\n\n\n"
        "def a(p, types=None):\n    return MODEL.run(p).answer\n"
    )
    assert "options=acme_types.RunConfig(heat=1)" in produced


# The constructor's arguments are pasted into every call, so each is re-read at every call site.

# A module-level model's one call, below whatever builds it.
CALLED = "\n\n\ndef a(p):\n    return MODEL.run(p).answer\n"


@pytest.mark.parametrize(
    "body",
    [
        "MODEL_NAME = 'm'\nMODEL = sdk.Model(MODEL_NAME)"
        + CALLED.replace("def a(p)", "def a(p, MODEL_NAME=None)"),
        "MODEL = sdk.Model(pick())" + CALLED,
        "def a(p, name):\n    m = sdk.Model(name)\n    name = 'other'\n"
        "    return m.run(p).answer\n",
        "MODEL = sdk.Model('m', settings={'heat': HEAT()})" + CALLED,
    ],
    ids=["shadowed-at-the-call", "a-call", "rebound", "a-call-in-the-configuration"],
)
def test_what_does_not_mean_the_same_at_the_call_refuses_the_group(body: str) -> None:
    _produced, edits = run(body)
    assert set(refusals(edits)) == {"ctor_argument_not_portable"}


@pytest.mark.parametrize(
    "body",
    [
        "x = 1\nITEMS = ['m']\nMODEL = sdk.Model([x for x in ITEMS])" + CALLED,
        "x = 1\nITEMS = ['m']\nMODEL = sdk.Model({x for x in ITEMS})" + CALLED,
        "x = 1\nITEMS = ['m']\nMODEL = sdk.Model({x: x for x in ITEMS})" + CALLED,
        "x = 1\nITEMS = ['m']\nMODEL = sdk.Model((x for x in ITEMS))" + CALLED,
        "MODEL = sdk.Model((chosen := 'm'))" + CALLED,
        "async def a(p, name):\n    m = sdk.Model(await name)\n    return m.run(p).answer\n",
        "def a(p):\n    m = sdk.Model((yield))\n    return m.run(p).answer\n",
    ],
    ids=["a-list", "a-set", "a-mapping", "a-generator", "an-assignment", "an-await", "a-yield"],
)
def test_what_runs_when_it_is_read_refuses_the_group(body: str) -> None:
    """Each acts again when re-evaluated at a call site, though its names alone would pass.

    `x = 1` makes the loop variable look module-bound; a generator does not survive re-iteration.
    """
    _produced, edits = run(body)
    assert set(refusals(edits)) == {"ctor_argument_not_portable"}


@pytest.mark.parametrize(
    "body",
    [
        "MODEL_NAME = 'm'\nMODEL = sdk.Model(MODEL_NAME)" + CALLED,
        "def a(p, name):\n    m = sdk.Model(name)\n    return m.run(p).answer\n",
        "MODEL = sdk.Model(('m' if True else None))" + CALLED,
        "import cfg\n\nMODEL = sdk.Model(cfg.NAME)" + CALLED,
    ],
    ids=[
        "a-module-constant",
        "a-parameter-in-its-own-function",
        "an-expression-of-literals",
        "an-attribute-of-a-module",
    ],
)
def test_what_means_the_same_at_the_call_travels(body: str) -> None:
    _produced, edits = run(body)
    assert set(refusals(edits)) == {None}
