"""A module the new SDK keeps: only `symbols` is legacy, calls stay on the module, and the pin is
one for both APIs. `acme.kit` is invented, so nothing here reads the openai pack's spellings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import acme
import acme_kept as kit
import pytest

from obelize.models import Edit
from obelize.packs import loader
from obelize.packs.schema import PackDocument
from obelize.scan import manifests
from obelize.transforms.kinds.rewrite_call import MODULE_BAILS, RewriteCall, _Tree

HEADER = "import acme.kit\n\n"


def found(source: str) -> list[tuple[int, str, str | None, str | None]]:
    """What the scan reports, as (line, kind, symbol, bail)."""
    result = acme.scan(source, kit.SPEC)
    return [(f.line, f.kind, f.symbol, f.bail) for f in result.findings]


def rewrite(body: str, header: str = HEADER) -> tuple[str, list[Edit]]:
    return acme.transform(f"{header}{body}", kit.SAY, kit.FETCH, spec=kit.SPEC)


def reasons(edits: list[Edit]) -> list[str | None]:
    return [row.reason for row in edits]


# The scan: what is legacy, and what only reaches the module.


def test_the_module_and_what_the_new_sdk_kept_are_no_finding() -> None:
    source = (
        "import acme.kit\n"
        "acme.kit.token = 'k'\n"
        "client = acme.kit.Client()\n"
        "print(acme.kit.token)\n"
        "acme.kit.talk.say(who='a')\n"
    )
    assert found(source) == []


def test_a_name_in_symbols_is_legacy_however_it_is_reached() -> None:
    source = (
        "import acme.kit as kit\n"
        "from acme.kit import Greeter, Client\n"
        "import acme.kit.legacy\n"
        "kit.Greeter.say(name='a')\n"
        "Greeter.say(name='b')\n"
    )
    assert found(source) == [
        (2, "import", "acme.kit.Greeter", None),
        (3, "import", "acme.kit.legacy", "flag_only_surface"),
        (4, "call", "acme.kit.Greeter.say", None),
        (5, "call", "acme.kit.Greeter.say", None),
    ]


def test_a_symbol_is_legacy_by_dotted_segment_not_by_prefix() -> None:
    assert found("import acme.kit\nacme.kit.Greeterish = 1\nacme.kit.proxy = 2\n") == [
        (3, "attribute", "acme.kit.proxy", "flag_only_surface")
    ]


def test_the_module_used_as_a_value_escapes_the_scan() -> None:
    """`kit.Greeter` would no longer resolve, so the file is withheld, as for any legacy module."""
    assert found("import acme.kit\nkit = acme.kit\nkit.Greeter.say(name='a')\n") == [
        (2, "attribute", "acme.kit", "module_alias_rebound")
    ]


@pytest.mark.parametrize(
    ("name", "symbol"), [("Greeter", "acme.kit.Greeter"), ("token", "acme.kit")]
)
def test_getattr_on_the_module_names_what_escapes_the_scan(name: str, symbol: str) -> None:
    """A legacy name is the symbol; a kept one only lets the module itself escape as a value."""
    rows = acme.scan(f"import acme.kit\ngetattr(acme.kit, '{name}')\n", kit.SPEC).findings
    assert [(f.symbol, f.bail) for f in rows] == [(symbol, "module_alias_rebound")]


def test_a_star_import_of_the_module_is_found_though_the_module_is_no_symbol() -> None:
    rows = acme.scan("from acme.kit import *\nGreeter.say(name='a')\n", kit.SPEC).findings
    assert (rows[0].kind, rows[0].bail) == ("star_import", "star_import")


def test_a_mention_of_a_kept_name_is_prose_and_one_of_a_legacy_name_is_a_mention() -> None:
    source = "import acme.kit\n# acme.kit.token is read here\n# acme.kit.Greeter.say was\n"
    rows = acme.scan(source, kit.SPEC).findings
    assert [(f.line, f.kind, f.symbol) for f in rows] == [
        (3, "text_mention", "acme.kit.Greeter.say")
    ]


def test_a_patch_target_is_flagged_only_when_it_names_a_legacy_symbol() -> None:
    source = (
        "from unittest import mock\nmock.patch('acme.kit.Client')\nmock.patch('acme.kit.legacy')\n"
    )
    rows = acme.scan(source, kit.SPEC).findings
    assert [(f.line, f.confidence_reason) for f in rows] == [(3, "mock_patch_target")]


def test_a_read_off_a_calls_result_is_the_calls_own_row() -> None:
    """`f(...).reply.text` is not a second usage, and not a link in a chain that hides the call."""
    source = "import acme.kit\nacme.kit.Greeter.say(name='a').reply.text.strip()\n"
    assert found(source) == [(2, "call", "acme.kit.Greeter.say", None)]


# The rewrite: a call stays on the root the author wrote.


def test_a_call_is_rooted_on_whatever_name_the_file_bound_the_module_to() -> None:
    code, edits = rewrite("acme.kit.Greeter.say(name='a')\n")
    assert code == f"{HEADER}acme.kit.talk.say(who='a')\n"
    code, _ = rewrite("kit.Greeter.say(name='a')\n", "import acme.kit as kit\n")
    assert code == "import acme.kit as kit\nkit.talk.say(who='a')\n"
    assert [row.status for row in edits] == ["auto"]


def test_a_positional_argument_is_lifted_and_a_keyword_is_carried_by_name() -> None:
    code, _ = rewrite("acme.kit.Greeter.say('a', loud=True, times=2)\n")
    assert code.splitlines()[-1] == "acme.kit.talk.say(who='a', loud=True, times=2)"


@pytest.mark.parametrize(
    ("call", "reason"),
    [
        ("acme.kit.Greeter.say(name='a', mood='x')", "unsupported_kwarg"),
        ("acme.kit.Greeter.say('a', True)", "positional_arg_ambiguous"),
        ("acme.kit.Greeter.say(**options)", "unsupported_kwarg"),
        ("acme.kit.Greeter.say('a', name='b')", "positional_arg_ambiguous"),
    ],
)
def test_an_argument_the_pack_does_not_list_refuses_the_call(call: str, reason: str) -> None:
    code, edits = rewrite(f"{call}\n")
    assert reasons(edits) == [reason]
    assert code == f"{HEADER}{call}\n"


def test_a_call_reached_by_a_from_import_has_no_root_to_keep() -> None:
    code, edits = rewrite("Greeter.say(name='a')\n", "from acme.kit import Greeter\n")
    assert reasons(edits) == ["from_import_unmigrated_symbol"]
    assert code == "from acme.kit import Greeter\nGreeter.say(name='a')\n"
    assert {"from_import_unmigrated_symbol"} == MODULE_BAILS


def test_a_rule_rooted_on_the_module_neither_consumes_a_symbol_nor_reads_a_client() -> None:
    assert RewriteCall(kit.SAY).consumes == frozenset()
    assert RewriteCall(kit.SAY).client_readers == frozenset()
    assert RewriteCall(acme.MEASURE).consumes == {"acme.sdk.measure"}
    assert RewriteCall(acme.MEASURE).client_readers == {"acme.sdk.measure"}


# result_paths: the reads that carry, and nothing else.

CALL = "acme.kit.Greeter.say(name='a')"


@pytest.mark.parametrize(
    "body",
    [
        f"{CALL}\n",
        f"print({CALL}.reply.text)\n",
        f"r = {CALL}\nprint(r.reply.text, r.spent.words)\n",
        f"r = {CALL}\nr.reply.text.upper()\n",
        f"r = {CALL}\n",
        f"def f():\n    r = {CALL}\n    return [r.reply.text, r.spent.words]\n",
        f"r = {CALL}\ndef g():\n    return r.reply.text\n",
    ],
)
def test_a_result_read_only_along_a_listed_path_is_carried(body: str) -> None:
    _, edits = rewrite(body)
    assert [row.status for row in edits] == ["auto"], body


@pytest.mark.parametrize(
    "body",
    [
        f"{CALL}['reply']\n",
        f"r = {CALL}\nr['reply']\n",
        f"r = {CALL}\nr.get('reply')\n",
        f"r = {CALL}\nr.reply\n",
        f"r = {CALL}\nr.reply.words\n",
        f"r = {CALL}\nr.spent\n",
        f"r = {CALL}\nfor part in r:\n    pass\n",
        f"r = {CALL}\nr.reply.text, r\n",
        f"r = {CALL}\nreturn_it = r\n",
        f"def f():\n    return {CALL}\n",
        f"def f():\n    r = {CALL}\n    return r\n",
        f"a, b = {CALL}\n",
        f"r = s = {CALL}\n",
        f"r: object = {CALL}\n",
        f"r = {CALL}\nr.reply.text\nr.nothing\n",
    ],
)
def test_a_result_read_any_other_way_refuses_the_call(body: str) -> None:
    code, edits = rewrite(body)
    assert reasons(edits) == ["response_shape_changed"], body
    assert "talk.say" not in code


# A part of the result in a name, and a loop over its items.

ROWS = "acme.kit.Quote.get(symbol='x')"


@pytest.mark.parametrize(
    "body",
    [
        f"r = {CALL}\nm = r.reply\nprint(m.text)\n",
        f"r = {CALL}\nm = r.reply\nn = m\nprint(n.text)\n",
        f"m = {CALL}.reply\nprint(m.text)\n",
        f"r = {CALL}\nm = r.reply\n",
        f"r = {ROWS}\nfor row in r.rows:\n    print(row.price)\n",
        f"r = {ROWS}\nfor row in r.rows:\n    pass\n",
        f"print([row.price for row in {ROWS}.rows])\n",
        f"r = {ROWS}\nfirst = r.rows[0]\nprint(first.price)\n",
        f"def f():\n    r = {ROWS}\n    return [row.price for row in r.rows]\n",
    ],
)
def test_a_part_of_the_result_in_a_name_or_a_loop_is_read_on_along_the_path(body: str) -> None:
    code, edits = rewrite(body)
    assert [row.status for row in edits] == ["auto"], body
    assert "talk.say" in code or "quotes.fetch" in code


@pytest.mark.parametrize(
    "body",
    [
        f"r = {CALL}\nm = r.reply\nuse(m)\n",
        f"r = {CALL}\nm = r.reply\nm.words\n",
        f"r = {CALL}\nm = r.reply\nprint(m.text, m)\nx = [m]\n",
        f"def f():\n    r = {CALL}\n    m = r.reply\n    return m\n",
        f"r = {CALL}\nfor x in r.reply:\n    print(x)\n",
        f"r = {CALL}\nm, n = r.reply\n",
        f"r = {CALL}\nm: object = r.reply\n",
        f"r = {CALL}\nm = n = r.reply\n",
        f"r = {CALL}\nprint(*r.reply)\n",
        f"r = {CALL}\nprint(r.reply.words)\n",
        f"r = {ROWS}\nfor row in r.rows:\n    use(row)\n",
        f"r = {ROWS}\nfor row in r.rows:\n    print(row.price, row.other)\n",
        f"r = {ROWS}\nfor a, b in r.rows:\n    print(a)\n",
        f"r = {ROWS}\nfor row in enumerate(r.rows):\n    pass\n",
        f"r = {ROWS}\nfor row in r.rows[0:2]:\n    pass\n",
        f"print({CALL})\n",
        f"r = {CALL}\nprint(r)\n",
        f"r = {CALL}\nm = r.reply\nprint(m)\n",
        f"class A:\n    m = {CALL}.reply\n    x = m.text\n",
        f"m = {CALL}.reply\nprint(m.text, locals())\n",
    ],
)
def test_a_part_of_the_result_that_is_read_any_other_way_refuses_the_call(body: str) -> None:
    code, edits = rewrite(body)
    assert reasons(edits) == ["response_shape_changed"], body
    assert "talk.say" not in code
    assert "quotes.fetch" not in code


@pytest.mark.parametrize(
    ("body", "lines"),
    [
        (
            f"r = {CALL}\nm = r['reply']\nprint(m['text'])\n",
            ["m = r.reply", "print(m.text)"],
        ),
        (
            f"m = {CALL}['reply']\nn = m\nprint(n['text'])\n",
            ["m = acme.kit.talk.say(who='a').reply", "n = m", "print(n.text)"],
        ),
        (
            f"r = {ROWS}\nfor row in r['rows']:\n    print(row['price'])\n",
            ["for row in r.rows:", "    print(row.price)"],
        ),
        (
            f"print([row['price'] for row in {ROWS}['rows']])\n",
            ["print([row.price for row in acme.kit.quotes.fetch(symbol='x').rows])"],
        ),
        (
            f"r = {ROWS}\nfirst = r['rows'][0]\nprint(first['price'], first.price)\n",
            ["first = r.rows[0]", "print(first.price, first.price)"],
        ),
    ],
)
def test_a_key_read_through_a_name_is_the_attribute_of_that_name(
    body: str, lines: list[str]
) -> None:
    code, edits = rewrite(body)
    assert {row.status for row in edits} == {"auto"}, body
    assert code.splitlines()[-len(lines) :] == lines


@pytest.mark.parametrize(
    "body",
    [
        f"r = {CALL}\nm = r['reply']\nm = {{}}\nprint(m['text'])\n",
        f"r = {CALL}\nm = r['reply']\ndef g():\n    return m['text']\n",
        f"r = {CALL}\nm = r['reply']\ng = lambda: m['text']\n",
        f"r = {CALL}\nm = r['reply']\ntry:\n    x = m['text']\nexcept KeyError:\n    x = ''\n",
        f"r = {CALL}\ntry:\n    m = r['reply']\nexcept LookupError:\n    m = None\n",
        f"r = {CALL}\nm = r['reply']\nprint(f\"{{m['text']=}}\")\n",
        f"r = {ROWS}\nprint([1 for row in r['rows']if row.price])\n",
        f"row = {{}}\nr = {ROWS}\nfor row in r['rows']:\n    print(row['price'])\n",
        f"r = {ROWS}\nfor row in r['rows']:\n    print(row['other'])\n",
    ],
)
def test_a_key_read_through_a_name_that_may_hold_something_else_refuses_the_call(
    body: str,
) -> None:
    code, edits = rewrite(body)
    assert reasons(edits) == ["response_shape_changed"], body
    assert "talk.say" not in code
    assert "quotes.fetch" not in code


def test_a_name_that_may_hold_something_else_is_read_by_attribute_through_a_name() -> None:
    """Only a key loses its dictionary: the attribute reads of the same code are carried."""
    body = f"m = {{}}\nr = {CALL}\nm = r.reply\nprint(m.text)\n"
    _, edits = rewrite(body)
    assert [row.status for row in edits] == ["auto"]
    _, edits = rewrite(body.replace("m.text", "m['text']").replace("r.reply", "r['reply']"))
    assert reasons(edits) == ["response_shape_changed"]


@pytest.mark.parametrize(
    "body",
    [
        # A walrus in a comprehension binds the function's name, which its own scope never lists.
        f"r = {CALL}\nm = r['reply']\nx = m['text']\nys = [y for y in [{{}}] if (m := y)]\n",
        f"r = {ROWS}\nfor row in r['rows']:\n    [1 for _ in [1] if (row := {{}})]\n"
        "    row['price']\n",
        f"r = {CALL}\nx = r['reply']['text']\n[1 for _ in [1] if (r := {{}})]\n",
        # A read above the binding in a loop is the second pass's, and links to a name outside.
        f"m = {{}}\ndef f():\n    r = {CALL}\n    for i in [1, 2]:\n        if i:\n"
        "            print(m['text'])\n        m = r['reply']\n",
        f"row = {{}}\ndef f():\n    r = {ROWS}\n    for i in [1, 2]:\n        if i:\n"
        "            print(row['price'])\n        for row in r['rows']:\n            pass\n",
        f"def f():\n    m = {{}}\n    def g():\n        r = {CALL}\n        for i in [1, 2]:\n"
        "            if i:\n                print(m['text'])\n            m = r['reply']\n",
        # A key read where a generator runs it later, outside the handler or the call's own frame.
        f"r = {CALL}\nm = r['reply']\ng = (m['text'] for _ in [1])\n",
        f"r = {ROWS}\ng = (row['price'] for row in r['rows'])\n",
        f"g = (row['price'] for row in {ROWS}['rows'])\n",
        f"r = {CALL}\nclass K:\n    x = r['reply']['text']\n",
        # A name that may hold something else hands that on to the name that copies it.
        f"r = {CALL}\nm = r['reply']\nm = {{}}\nn = m\nprint(n['text'])\n",
        # One name bound to two parts of the result is read along each of them.
        f"r = {CALL}\nm = r.spent\nm = r.reply\nprint(m.text)\n",
        # A dictionary-only operator reads the part and is no read of it.
        f"r = {CALL}\nm = r.reply\nm |= {{'x': 1}}\nprint(m.text)\n",
        f"r = {ROWS}\nfor row in r.rows:\n    row |= {{'x': 1}}\n    print(row.price)\n",
        f"r = {CALL}\nr |= {{}}\nprint(r.reply.text)\n",
        # A name read by its string: through a frame, a module's dictionary or an alias of `locals`.
        f"r = {CALL}\nm = r.reply\nprint(sys._getframe().f_locals['m']['text'])\n",
        f"r = {CALL}\nm = r.reply\nf = locals\nprint(f()['m'])\n",
        f"r = {CALL}\nm = r.reply\nprint(builtins.locals()['m'], m.text)\n",
        f"r = {CALL}\nm = r.reply\nev = eval\nprint(ev('m'), m.text)\n",
        f"r = {CALL}\nm = r.reply\nprint(sys.modules[__name__].__dict__['m'])\n",
    ],
)
def test_a_key_read_that_something_else_may_rebind_or_run_later_refuses_the_call(
    body: str,
) -> None:
    code, edits = rewrite(body)
    assert reasons(edits) == ["response_shape_changed"], body
    assert "talk.say" not in code
    assert "quotes.fetch" not in code


@pytest.mark.parametrize(
    "body",
    [
        f"r = {CALL}\nm = r.reply\nm = m\nprint(m.text)\n",
        f"r = {CALL}\na = r.reply\nb = a\na = b\nprint(a.text)\n",
        f"r = {CALL}\nm = r['reply']\nm = m\nprint(m['text'])\n",
        f"r = {CALL}\nm0 = r.reply\n"
        + "".join(f"m{n + 1} = m{n}\n" for n in range(1500))
        + "print(m1500.text)\n",
    ],
)
def test_a_name_that_takes_itself_or_a_long_chain_of_names_ends_the_walk(
    body: str,
) -> None:
    _, edits = rewrite(body)
    assert len(edits) == 1


def test_a_script_that_reuses_its_names_walks_each_use_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reads of a result's name are the same for every call bound to it, and listed once."""
    climbs: list[int] = []
    climb = _Tree._climb

    def counted(self: _Tree, *args: Any) -> Any:
        climbs.append(1)
        return climb(self, *args)

    monkeypatch.setattr(_Tree, "_climb", counted)
    body = "".join(
        f"r = {CALL}\nm = r.reply\nprint(m.text)\nn = m\nprint(n.text)\n" for _ in range(60)
    )
    _, edits = rewrite(body)
    assert len(edits) == 60
    assert len(climbs) < 60 * 6


FETCH_CALL = "acme.kit.Quote.get(symbol='x')"
OTHER = CALL.replace("'a'", "'b'")
# A call whose argument is a keyed read of another: each is rewritten once, whichever is read first.
NESTED = OTHER.replace("'b'", f"{CALL}['reply']['text']")


@pytest.mark.parametrize(
    ("body", "line"),
    [
        (f"print({CALL}['reply']['text'])\n", "print(acme.kit.talk.say(who='a').reply.text)"),
        (
            f"r = {CALL}\nprint(r['reply']['text'], r['spent']['words'])\n",
            "print(r.reply.text, r.spent.words)",
        ),
        (
            f"r = {CALL}\nprint(r.reply['text'], r['spent'].words)\n",
            "print(r.reply.text, r.spent.words)",
        ),
        (f'r = {CALL}\nprint(r["reply"][ u"text" ])\n', "print(r.reply.text)"),
        (f"r = {CALL}\nprint((r['reply'])['text'])\n", "print((r.reply).text)"),
        (
            f"p = {FETCH_CALL}['rows'][0]['price']\n",
            "p = acme.kit.quotes.fetch(symbol='x').rows[0].price",
        ),
        (f"r = {CALL}\nprint(r['reply']['text'].upper()[0])\n", "print(r.reply.text.upper()[0])"),
        (
            f"r = {CALL}\nprint([r['reply']['text'] for _ in 'ab'])\n",
            "print([r.reply.text for _ in 'ab'])",
        ),
        (f"r = {CALL}\nprint(f\"{{r['reply']['text']}}\")\n", 'print(f"{r.reply.text}")'),
        (f"r = {CALL}\nx = r['reply']['text'] or 1\n", "x = r.reply.text or 1"),
        (
            f"x = {OTHER}['reply']['text'] + {CALL}['reply']['text']\n",
            "x = acme.kit.talk.say(who='b').reply.text + acme.kit.talk.say(who='a').reply.text",
        ),
        (
            f"x = {NESTED}['reply']['text']\n",
            "x = acme.kit.talk.say(who=acme.kit.talk.say(who='a').reply.text).reply.text",
        ),
    ],
)
def test_a_string_key_along_a_listed_path_is_read_as_the_attribute_of_that_name(
    body: str, line: str
) -> None:
    code, edits = rewrite(body)
    assert {row.status for row in edits} == {"auto"}, body
    assert code.splitlines()[-1] == line


@pytest.mark.parametrize(
    "body",
    [
        f"r = {CALL}\nr['reply']['text'] = 'x'\n",
        f"r = {CALL}\nr['reply']['text'] += 'x'\n",
        f"r = {CALL}\ndel r['reply']['text']\n",
        f"r = {CALL}\nr['reply',]['text']\n",
        f"r = {CALL}\nr['other']\n",
        f"r = {CALL}\nr['reply']['words']\n",
        f"r = {CALL}\nr[key]['text']\n",
        f"r = {CALL}\nr['re' 'ply']['text']\n",
        f"r = {CALL}\nr[f'reply']['text']\n",
        f"r = {CALL}\nr[b'reply']['text']\n",
        f"r = {CALL}\nr['reply'].get('text')\n",
        f"p = {FETCH_CALL}['rows']['[]']['price']\n",
        f"r = {CALL}\nprint(f\"{{r['reply']['text']=}}\")\n",
        f"r = {CALL}\nr[*'reply']['text']\n",
        f"r = {CALL}\nx = r['reply']['text']or 1\n",
        f"r = {CALL}\nx = 1 if r['reply']['text']else 2\n",
        f"r = {CALL}\nx = [q for q in r['reply']['text']if q]\n",
    ],
)
def test_a_key_the_pack_does_not_list_or_a_write_through_it_refuses_the_call(body: str) -> None:
    code, edits = rewrite(body)
    assert reasons(edits) == ["response_shape_changed"], body
    assert "talk.say" not in code


@pytest.mark.parametrize(
    "body",
    [
        f"r = {{}}\nif again:\n    r = {CALL}\nprint(r['reply']['text'])\n",
        f"def f(r):\n    r = {CALL}\n    return r['reply']['text']\n",
        f"r = {CALL}\nfor r in [{{}}]:\n    print(r['reply']['text'])\n",
        f"with open('f') as r:\n    pass\nr = {CALL}\nprint(r['reply']['text'])\n",
        f"def f():\n    r = {CALL}\n    def g():\n        nonlocal r\n        r = {{}}\n"
        "    return r['reply']['text']\n",
        f"def f():\n    global R\n    R = {CALL}\n    return R['reply']['text']\n"
        "def g():\n    global R\n    R = {}\n",
    ],
)
def test_a_name_that_may_hold_something_else_is_not_read_by_key(body: str) -> None:
    """The dictionary it may hold would lose its keys; a read by attribute is no such risk."""
    code, edits = rewrite(body)
    assert reasons(edits) == ["response_shape_changed"], body
    assert "talk.say" not in code
    _, edits = rewrite(body.replace("['reply']['text']", ".reply.text"))
    assert [row.status for row in edits] == ["auto"], body


@pytest.mark.parametrize(
    "body",
    [
        f"r = {CALL}\ndef g():\n    return r['reply']['text']\n",
        f"r = {CALL}\ng = lambda: r['reply']['text']\n",
        "from shared import *\n\n\ndef cached():\n    return r['reply']['text']\n\n\n"
        f"def fresh():\n    r = {CALL}\n    return r['reply']['text']\n",
    ],
)
def test_a_read_by_key_must_run_where_the_call_does_and_be_linked_to_it(body: str) -> None:
    """A closure runs when it is called, and an unlinked name may be a module's own."""
    code, edits = rewrite(body)
    assert reasons(edits) == ["response_shape_changed"], body
    assert "talk.say" not in code


@pytest.mark.parametrize(
    ("prelude", "handler", "carried"),
    [
        ("", "KeyError", False),
        ("", "LookupError", False),
        ("", "(ValueError, KeyError)", False),
        ("", "*KeyError", False),
        ("EXC = (KeyError, ValueError)\n", "EXC", False),
        ("class Mine(Exception):\n    pass\n", "Mine", False),
        ("", "Undefined", False),
        ("import socket\n", "socket.timeout", True),
        ("", "Exception", True),
        ("", "AttributeError", True),
        ("", "ValueError", True),
        ("", "", True),
    ],
)
def test_a_handler_for_a_missing_key_would_miss_the_attribute_error_that_replaces_it(
    prelude: str, handler: str, carried: bool
) -> None:
    body = f"{prelude}r = {CALL}\ntry:\n    x = r['reply']['text']\nexcept {handler}:\n    x = ''\n"
    code, edits = rewrite(body)
    assert [row.status for row in edits] == (["auto"] if carried else ["needs_review"]), handler
    assert ("x = r.reply.text" in code) is carried


@pytest.mark.parametrize(
    ("manager", "carried"),
    [
        ("contextlib.suppress(KeyError)", False),
        ("ignore(KeyError)", False),
        ("contextlib.nullcontext()", True),
        ("lock", True),
    ],
)
def test_a_suppress_around_a_read_would_hide_the_error_that_replaces_it(
    manager: str, carried: bool
) -> None:
    body = (
        "import contextlib\nfrom contextlib import suppress as ignore\n"
        f"r = {CALL}\nwith {manager}:\n    x = r['reply']['text']\n"
    )
    _, edits = rewrite(body)
    assert [row.status for row in edits] == (["auto"] if carried else ["needs_review"]), manager


def test_a_read_is_rewritten_only_when_its_call_is() -> None:
    """The call is refused last of all, so its reads are recorded only once it has passed."""
    say = kit.SAY.model_copy(
        update={
            "params": kit.SAY.params.model_copy(
                update={"legacy_error_modules": ("acme.kit.errors",)}
            )
        }
    )
    body = f"try:\n    print({CALL}['reply']['text'])\nexcept acme.kit.errors.Failure:\n    pass\n"
    code, edits = acme.transform(f"{HEADER}{body}", say, kit.FETCH, spec=kit.SPEC)
    assert reasons(edits) == ["error_class_changed"]
    assert "print(acme.kit.Greeter.say(name='a')['reply']['text'])" in code


def test_an_integer_subscript_is_a_step_on_the_path_and_any_other_is_not() -> None:
    fetch = FETCH_CALL
    for index in ("0", "-1", "12"):
        code, edits = rewrite(f"p = {fetch}.rows[{index}].price\n")
        assert [row.status for row in edits] == ["auto"], index
        assert "quotes.fetch(symbol='x')" in code
    for index in ("i", "'a'", "0:1", "0, 1", "len(x) - 1"):
        _, edits = rewrite(f"p = {fetch}.rows[{index}].price\n")
        assert reasons(edits) == ["response_shape_changed"], index


def test_a_path_may_not_go_on_past_its_leaf_to_a_name_the_pack_never_listed() -> None:
    """`price` is a leaf, so what is called on it is the leaf's own business."""
    _, edits = rewrite("acme.kit.Quote.get(symbol='x').rows[0].price.real\n")
    assert [row.status for row in edits] == ["auto"]
    _, edits = rewrite("acme.kit.Quote.get(symbol='x').rows.append(1)\n")
    assert reasons(edits) == ["response_shape_changed"]


def test_a_read_above_the_assignment_is_a_read_of_the_result_on_the_loops_next_pass() -> None:
    """libcst links that read to no assignment, so the rule looks for it by name."""
    body = (
        "def chat():\n    while True:\n        if again:\n            print(r['reply'])\n"
        f"        r = {CALL}\n        print(r.reply.text)\n"
    )
    code, edits = rewrite(body)
    assert reasons(edits) == ["response_shape_changed"]
    assert "talk.say" not in code
    _, edits = rewrite(body.replace("print(r['reply'])", "print(r.reply.text)"))
    assert [row.status for row in edits] == ["auto"]


def test_a_result_kept_in_a_class_body_is_read_as_an_attribute_of_the_class() -> None:
    body = f"class A:\n    r = {CALL}\n    def g(self):\n        return self.r['reply']\n"
    code, edits = rewrite(body)
    assert reasons(edits) == ["response_shape_changed"]
    assert "talk.say" not in code


def test_a_call_in_an_f_string_stays_on_one_line_for_a_python_that_allows_no_other() -> None:
    long = "acme.kit.Greeter.say(name='a', loud=True, times=2).reply.text"
    code, edits = rewrite(
        f'print(f"x {{{long}}} and enough text after it to pass the width xxxxxx")\n'
    )
    assert [row.status for row in edits] == ["auto"]
    assert code.splitlines()[-1].startswith('print(f"x {acme.kit.talk.say(who=')
    assert len(code.splitlines()) == 3


# The pin: one distribution on both sides, so the repository goes together.

SOURCE = "import acme.kit\n\nreply = acme.kit.Greeter.say(name='a')\nprint(reply.reply.text)\n"
BROKEN = "import acme.kit\n\nreply = acme.kit.Greeter.say(name='b')\nprint(reply['reply'])\n"
PINNED = "acme-kit==1.5\n"


def migrate(
    root: Path, files: dict[str, str], pack: object = kit.PACK, spec: object = kit.SPEC
) -> tuple[dict[str, str], list[tuple[str, int, str, str | None]]]:
    run = acme.repository(root, files, spec=spec, pack=pack)  # type: ignore[arg-type]
    after = {**files, **{row.path: row.after.decode() for row in run.outcomes}}
    rows: list[tuple[str, int, str, str | None]] = [
        (row.path, row.line, row.status, row.reason) for row in run.edits
    ]
    return after, rows


def test_a_distribution_on_both_sides_is_coupled_and_two_distributions_are_not() -> None:
    assert manifests.coupled(kit.SPEC)
    assert not manifests.coupled(acme.SPEC)


def test_a_repository_that_migrates_whole_moves_its_files_and_its_pin_together(
    tmp_path: Path,
) -> None:
    after, rows = migrate(tmp_path, {"a.py": SOURCE, "b.py": SOURCE, "requirements.txt": PINNED})
    assert after["a.py"].splitlines()[2] == "reply = acme.kit.talk.say(who='a')"
    assert after["b.py"] == after["a.py"]
    assert after["requirements.txt"] == "acme-kit>=2,<3\n"
    assert {status for *_, status, _ in rows} == {"auto"}


def test_a_dictionary_style_read_no_longer_holds_the_repository(tmp_path: Path) -> None:
    keyed = SOURCE.replace("reply.reply.text", "reply['reply']['text']")
    after, rows = migrate(tmp_path, {"a.py": keyed, "requirements.txt": PINNED})
    assert after["a.py"] == SOURCE.replace(
        "acme.kit.Greeter.say(name='a')", "acme.kit.talk.say(who='a')"
    )
    assert after["requirements.txt"] == "acme-kit>=2,<3\n"
    assert {status for *_, status, _ in rows} == {"auto"}


def test_one_file_left_behind_leaves_every_file_and_the_pin_as_they_were(tmp_path: Path) -> None:
    files = {"a.py": SOURCE, "b.py": BROKEN, "requirements.txt": PINNED}
    after, rows = migrate(tmp_path, files)
    assert after == files
    assert sorted((path, reason) for path, _, _, reason in rows) == [
        ("a.py", "repo_not_fully_migrated"),
        ("b.py", "response_shape_changed"),
        ("requirements.txt", "repo_not_fully_migrated"),
    ]


def test_a_withheld_row_of_any_kind_holds_the_repository(tmp_path: Path) -> None:
    flagged = "import acme.kit\nacme.kit.proxy = 'p'\n"
    after, rows = migrate(tmp_path, {"a.py": SOURCE, "b.py": flagged, "requirements.txt": PINNED})
    assert after["a.py"] == SOURCE
    assert after["requirements.txt"] == PINNED
    assert ("a.py", 3, "needs_review", "repo_not_fully_migrated") in rows


def test_a_pin_the_code_no_longer_needs_is_not_an_edit(tmp_path: Path) -> None:
    after, rows = migrate(
        tmp_path,
        {"a.py": "import acme.kit\nclient = acme.kit.Client()\n", "requirements.txt": PINNED},
    )
    assert rows == []
    assert after["requirements.txt"] == PINNED


def test_a_hold_in_the_manifest_alone_holds_the_files_too(tmp_path: Path) -> None:
    """A module only the old version installed, imported with no manifest declaring it."""
    pack = kit.PACK.model_copy(
        update={
            "match": kit.PACK.match.model_copy(update={"transitive": {"acme.wire": "acme-wire"}})
        }
    )
    spec = kit.SPEC.model_copy(update={"transitive_modules": (acme.SPEC.transitive_modules[0],)})
    files = {"a.py": SOURCE + "import acme.wire\n", "requirements.txt": PINNED}
    held, rows = migrate(tmp_path / "held", files, pack, spec)
    assert held["a.py"] == files["a.py"]
    assert ("requirements.txt", 1, "needs_review", "transitive_dependency_in_use") in rows
    assert ("a.py", 3, "needs_review", "repo_not_fully_migrated") in rows
    declared = {**files, "requirements.txt": PINNED + "acme-wire\n"}
    freed, _ = migrate(tmp_path / "freed", declared, pack, spec)
    assert freed["requirements.txt"].splitlines()[0] == "acme-kit>=2,<3"
    assert "talk.say" in freed["a.py"]


# Names the module's namespace reaches, and what a scan must not trip over.


@pytest.mark.parametrize(
    "fetch",
    ["importlib.import_module('acme.kit')", "__import__('acme.kit')", "sys.modules['acme.kit']"],
)
def test_the_module_fetched_by_its_name_is_a_dynamic_access(fetch: str) -> None:
    """Whatever it is bound to, its legacy names no longer meet an import statement."""
    assert found(f"import importlib, sys\nm = {fetch}\nm.Greeter\n") == [
        (2, "dynamic", "acme.kit", "flag_only_surface")
    ]


def test_the_namespace_of_the_module_is_no_way_round_its_symbols() -> None:
    assert found("import acme.kit\nacme.kit.__dict__['Greeter']\n") == [
        (2, "attribute", "acme.kit", "module_alias_rebound")
    ]
    assert found("import acme.kit\nprint(acme.kit.__version__)\n") == []


def test_a_star_import_is_found_only_where_it_could_bring_a_legacy_name() -> None:
    assert found("from acme.kit.extras import *\n") == []
    assert [row[1] for row in found("from acme.kit import *\n")] == ["star_import"]
    assert [row[1] for row in found("from acme.kit.legacy import *\n")] == ["star_import"]


def test_a_name_bound_by_a_match_pattern_does_not_stop_the_scan() -> None:
    source = (
        "import acme.kit\n\n\ndef f(r):\n    match r:\n"
        "        case {'k': value}:\n            return value\n"
    )
    assert found(source) == []
    assert acme.scan("import acme.sdk\n" + source.split("\n", 1)[1], acme.SPEC).findings


def test_a_read_off_a_calls_result_is_still_its_own_row_where_the_module_is_not_shared() -> None:
    """The row is the guard against a read nobody vetted; only a shared pack has result_paths."""
    result = acme.scan("import acme.sdk as sdk\nsdk.lookup('kinds/a').other\n", acme.SPEC)
    assert ("attribute", "acme.sdk.lookup.other") in [(f.kind, f.symbol) for f in result.findings]


# The pin: which declarations are the old API, and which the rule cannot write.


@pytest.mark.parametrize("pin", ["acme-kit==2.3", "acme-kit>=2", "acme-kit~=2.1", "acme-kit>=2,<3"])
def test_a_declaration_that_already_pins_the_new_range_is_left_as_written(
    tmp_path: Path, pin: str
) -> None:
    files = {
        "a/app.py": SOURCE,
        "a/requirements.txt": PINNED,
        "b/requirements.txt": f"{pin}\n",
    }
    after, _rows = migrate(tmp_path, files)
    assert after["a/requirements.txt"] == "acme-kit>=2,<3\n"
    assert after["b/requirements.txt"] == f"{pin}\n"
    assert "talk.say" in after["a/app.py"]


def test_a_declaration_that_admits_the_old_api_is_rewritten_whatever_else_it_admits(
    tmp_path: Path,
) -> None:
    after, _rows = migrate(tmp_path, {"a.py": SOURCE, "requirements.txt": "acme-kit>=1.2,<3\n"})
    assert after["requirements.txt"] == "acme-kit>=2,<3\n"


@pytest.mark.parametrize(
    "pin",
    ["acme-kit[extra]==1.5", "acme-kit @ https://example.invalid/kit.whl"],
)
def test_a_pin_the_rule_cannot_write_holds_the_repository(tmp_path: Path, pin: str) -> None:
    files = {"a.py": SOURCE, "requirements.txt": f"{pin}\n"}
    after, rows = migrate(tmp_path, files)
    assert after == files
    assert ("requirements.txt", 1, "needs_review", "manifest_pin_shape_unsupported") in rows
    assert ("a.py", 3, "needs_review", "repo_not_fully_migrated") in rows


def test_a_coupled_pack_that_renames_a_module_holds_the_import_with_the_rest(
    tmp_path: Path,
) -> None:
    """An import row may carry the repository's atomicity code, like any other row."""
    document = acme.OLD_PACK.model_dump(by_alias=True, mode="json")
    document["to"]["package"] = "acme-old"
    document["changes"][2]["params"] = {
        "from_name": "acme-old",
        "to_name": "acme-old",
        "to_spec": ">=3",
    }
    pack = PackDocument.model_validate(document)
    spec = loader.to_scan_spec(
        loader.LoadedPack(
            pack=pack,
            sha256="0" * 64,
            data=b"",
            reference=pack.id,
            bundled=False,
            path=Path("pack.yaml"),
        )
    )
    assert manifests.coupled(spec)
    files = {
        "a.py": "import acme.old\n\nacme.old.Reader()\n",
        "b.py": "import acme.old\n\nacme.old.Registry()\n",
        "requirements.txt": "acme-old==2.1\n",
    }
    after, rows = migrate(tmp_path, files, pack, spec)
    assert after == files
    assert ("a.py", 1, "needs_review", "repo_not_fully_migrated") in rows
    assert ("requirements.txt", 1, "needs_review", "repo_not_fully_migrated") in rows


# What a second review found: more ways to reach the module, and names read by their strings.


@pytest.mark.parametrize(
    "fetch",
    [
        "sys.modules.get('acme.kit')",
        "sys.modules.pop('acme.kit')",
        "sys.modules.setdefault('acme.kit', None)",
        "pkgutil.resolve_name('acme.kit')",
        "importlib.import_module('.legacy', 'acme.kit')",
    ],
)
def test_the_module_or_a_legacy_name_fetched_by_a_call_is_a_dynamic_access(fetch: str) -> None:
    rows = found(f"import importlib, pkgutil, sys\nm = {fetch}\n")
    assert [(kind, bail) for _, kind, _, bail in rows] == [("dynamic", "flag_only_surface")]


@pytest.mark.parametrize(
    "fetch",
    [
        "importlib.import_module('.extras', 'acme.kit')",
        "importlib.import_module('.legacy', package)",
        "importlib.import_module('acme.kit.extras')",
    ],
)
def test_a_relative_fetch_is_read_against_its_package_and_a_kept_name_is_no_row(fetch: str) -> None:
    assert found(f"import importlib\npackage = 'x'\nm = {fetch}\n") == []


def test_a_name_in_a_string_annotation_is_not_the_module_used_as_a_value() -> None:
    source = (
        "from typing import Annotated\nimport acme.kit\n"
        "def f(c: 'acme.kit.Client', d: Annotated[int, 'acme-kit']) -> 'acme.kit': ...\n"
    )
    assert found(source) == []
    assert [row[2] for row in found("import acme.kit\ndef f(c: 'acme.kit.Greeter'): ...\n")] == [
        "acme.kit.Greeter"
    ]


@pytest.mark.parametrize(
    "read",
    [
        "print(locals()['r']['reply'])",
        "print('{r[reply]}'.format(**vars()))",
        "print(eval('r.reply.text'))",
        "exec('print(r)')",
        "print(globals()['r'])",
    ],
)
def test_a_result_in_a_file_that_reads_names_by_their_strings_is_refused(read: str) -> None:
    code, edits = rewrite(f"def f():\n    r = {CALL}\n    {read}\n")
    assert reasons(edits) == ["response_shape_changed"]
    assert "talk.say" not in code


def test_a_call_read_in_place_is_not_refused_for_a_name_read_elsewhere() -> None:
    body = f"print({CALL}.reply.text)\nprint(locals())\n"
    _, edits = rewrite(body)
    assert [row.status for row in edits] == ["auto"]


def test_a_call_after_a_form_feed_is_wrapped_by_the_line_python_numbers() -> None:
    """`str.splitlines` counts a form feed as a line break, so the wrap read the line above."""
    long = "acme.kit.Greeter.say(name='" + "x" * 80 + "', loud=True, times=2)"
    code, edits = rewrite(f"\x0c\nprint({long}.reply.text)\n")
    assert [row.status for row in edits] == ["auto"]
    assert len(code.splitlines()) > 5


def test_a_file_that_is_both_source_and_manifest_is_one_outcome_in_one_run(tmp_path: Path) -> None:
    setup = (
        "import acme.kit\nfrom setuptools import setup\n\n"
        "r = acme.kit.Greeter.say(name='a')\nprint(r.reply.text)\n"
        "setup(name='a', install_requires=['acme-kit==1.5'])\n"
    )
    run = acme.repository(tmp_path, {"setup.py": setup}, spec=kit.SPEC, pack=kit.PACK)
    assert [row.path for row in run.outcomes] == ["setup.py"]
    (outcome,) = run.outcomes
    assert outcome.before.decode() == setup
    assert "acme.kit.talk.say(who='a')" in outcome.after.decode()
    assert "install_requires=['acme-kit>=2,<3']" in outcome.after.decode()
    assert [row.status for row in outcome.edits] == ["auto", "auto"]


def test_one_line_the_rule_cannot_write_holds_the_lines_it_can(tmp_path: Path) -> None:
    files = {"a.py": SOURCE, "requirements.txt": "acme-kit==1.5\nacme-kit[extra]==1.5\n"}
    after, rows = migrate(tmp_path, files)
    assert after == files
    assert ("requirements.txt", 1, "needs_review", "repo_not_fully_migrated") in rows
    assert ("requirements.txt", 2, "needs_review", "manifest_pin_shape_unsupported") in rows
