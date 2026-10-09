"""`rename_setting` on an invented shared module: `acme.kit.endpoint` is `acme.kit.address` in 2.x.

The new name needs its value to end in a slash, so a literal is written with one and anything else
is wrapped in the formatting the old release did. `acme.kit` is invented, so nothing here reads
the openai pack's spellings.
"""

from __future__ import annotations

from types import SimpleNamespace

import acme
import acme_kept as kit
import pytest

from obelize.models import Edit
from obelize.packs.schema import Change

HEADER = "import acme.kit\n\n"


def tune(body: str, *changes: Change, header: str = HEADER) -> tuple[str, list[Edit]]:
    code, edits = acme.transform(f"{header}{body}", *(changes or (kit.TUNE,)), spec=kit.SPEC)
    return code.removeprefix(header), edits


def reasons(edits: list[Edit]) -> list[str | None]:
    return [row.reason for row in edits]


@pytest.mark.parametrize(
    ("body", "written"),
    [
        ('acme.kit.endpoint = "http://h/v1"\n', 'acme.kit.address = "http://h/v1/"\n'),
        ("acme.kit.endpoint = 'http://h/v1'\n", "acme.kit.address = 'http://h/v1/'\n"),
        ('acme.kit.endpoint = "http://h/v1/"\n', 'acme.kit.address = "http://h/v1/"\n'),
        ('acme.kit.endpoint = ("http://h")\n', 'acme.kit.address = ("http://h/")\n'),
        ('acme.kit.endpoint = r"http://h"\n', 'acme.kit.address = r"http://h/"\n'),
        ('acme.kit.endpoint = """http://h"""\n', 'acme.kit.address = """http://h/"""\n'),
        ('acme.kit.endpoint = "a\\\\"\n', 'acme.kit.address = "a\\\\/"\n'),
        ('acme.kit.endpoint = ""\n', 'acme.kit.address = "/"\n'),
        ('acme.kit.endpoint = "http://h"  # proxy\n', 'acme.kit.address = "http://h/"  # proxy\n'),
        ('if x: acme.kit.endpoint = "u"\n', 'if x: acme.kit.address = "u/"\n'),
        ('a = 1; acme.kit.endpoint = "u"; b = 2\n', 'a = 1; acme.kit.address = "u/"; b = 2\n'),
    ],
)
def test_a_string_literal_is_written_with_the_ending_the_new_name_needs(
    body: str, written: str
) -> None:
    code, edits = tune(body)
    assert code == written
    assert [row.status for row in edits] == ["auto"]


@pytest.mark.parametrize(
    ("body", "written"),
    [
        ("acme.kit.endpoint = url\n", 'acme.kit.address = ("%s" % (url,)).rstrip("/") + "/"\n'),
        (
            'acme.kit.endpoint = os.environ["URL"]\n',
            'acme.kit.address = ("%s" % (os.environ["URL"],)).rstrip("/") + "/"\n',
        ),
        (
            'acme.kit.endpoint = f"http://{host}/v1"\n',
            'acme.kit.address = ("%s" % (f"http://{host}/v1",)).rstrip("/") + "/"\n',
        ),
        (
            'acme.kit.endpoint = "http://" "h"\n',
            'acme.kit.address = ("%s" % ("http://" "h",)).rstrip("/") + "/"\n',
        ),
        (
            'acme.kit.endpoint = b"http://h"\n',
            'acme.kit.address = ("%s" % (b"http://h",)).rstrip("/") + "/"\n',
        ),
        (
            "acme.kit.endpoint = a or b\n",
            'acme.kit.address = ("%s" % (a or b,)).rstrip("/") + "/"\n',
        ),
        (
            "acme.kit.endpoint = a, b\n",
            'acme.kit.address = ("%s" % ((a, b),)).rstrip("/") + "/"\n',
        ),
        (
            "def f():\n    acme.kit.endpoint = yield 1\n",
            'def f():\n    acme.kit.address = ("%s" % ((yield 1),)).rstrip("/") + "/"\n',
        ),
    ],
)
def test_any_other_value_is_formatted_and_given_the_ending(body: str, written: str) -> None:
    """The old release formatted the value into the address, so the wrapper formats it."""
    code, edits = tune(body)
    assert code == written
    assert [row.status for row in edits] == ["auto"]


def test_a_rename_with_no_ending_to_demand_leaves_the_value_alone() -> None:
    code, edits = tune("acme.kit.endpoint = url\n", kit.BARE)
    assert code == "acme.kit.address = url\n"
    assert [row.status for row in edits] == ["auto"]


@pytest.mark.parametrize(
    ("header", "body", "written"),
    [
        ("import acme.kit as kit\n\n", 'kit.endpoint = "u"\n', 'kit.address = "u/"\n'),
        ("from acme import kit\n\n", 'kit.endpoint = "u"\n', 'kit.address = "u/"\n'),
    ],
)
def test_the_root_stays_the_name_the_file_bound_the_module_to(
    header: str, body: str, written: str
) -> None:
    code, _ = tune(body, header=header)
    assert code == written


def test_a_value_another_rule_rewrites_is_rewritten_inside_the_wrapper() -> None:
    body = "acme.kit.endpoint = acme.kit.Quote.get(symbol='x')['rows'][0]['price']\n"
    code, edits = tune(body, kit.TUNE, kit.FETCH)
    assert code == (
        "acme.kit.address = "
        '("%s" % (acme.kit.quotes.fetch(symbol=\'x\').rows[0].price,)).rstrip("/") + "/"\n'
    )
    assert [row.status for row in edits] == ["auto", "auto"]


@pytest.mark.parametrize(
    "body",
    [
        "print(acme.kit.endpoint)\n",
        "x = acme.kit.endpoint\n",
        "acme.kit.endpoint += '/v1'\n",
        "del acme.kit.endpoint\n",
        "acme.kit.endpoint, other = 'u', 1\n",
        "acme.kit.endpoint = other = 'u'\n",
        "acme.kit.endpoint: str = 'u'\n",
        "acme.kit.endpoint = acme.kit.endpoint or 'u'\n",
        "for acme.kit.endpoint in urls:\n    pass\n",
        "with open(f) as acme.kit.endpoint:\n    pass\n",
        "from acme.kit import endpoint\nprint(endpoint)\n",
        "@acme.kit.endpoint\ndef f():\n    pass\n",
    ],
)
def test_any_use_of_the_old_name_but_a_plain_assignment_is_refused(body: str) -> None:
    code, edits = tune(body)
    assert "attribute_removed" in reasons(edits), body
    assert "address" not in code or "attribute_removed" in reasons(edits)


@pytest.mark.parametrize(
    "header",
    [
        "str = print\n",
        "def f(str): pass\n",
        "from helpers import str\n",
        "match x:\n    case str:\n        pass\n",
        "[str for str in x]\n",
        "if (str := 1):\n    pass\n",
        "del str\n",
    ],
)
def test_the_wrapper_names_no_builtin_so_a_file_rebinding_one_is_rewritten(header: str) -> None:
    code, edits = tune(f"{header}acme.kit.endpoint = url\n")
    assert code.endswith('acme.kit.address = ("%s" % (url,)).rstrip("/") + "/"\n')
    assert [row.status for row in edits] == ["auto"]


@pytest.mark.parametrize("value", ["http://h/v1", "http://h/v1/", "http://h/v1//", 7, None])
def test_the_wrapper_reads_as_the_old_release_formatted_the_value(value: object) -> None:
    """`"%s%s" % (setting, route)` and the wrapper agree, whatever the file calls `str`."""
    code, _ = tune("acme.kit.endpoint = url\n")
    assert isinstance(code, str)
    kit_ns = SimpleNamespace()
    scope = {"acme": SimpleNamespace(kit=kit_ns), "url": value, "str": print}
    exec(code, scope)  # noqa: S102 - the product's own output for a fixed input
    assert kit_ns.address == f"{str(value).rstrip('/')}/"


@pytest.mark.parametrize(
    "body",
    [
        'acme.kit.address = "http://h/v1"\nacme.kit.endpoint = "http://h/v1"\n',
        'acme.kit.endpoint = "http://h/v1"\nprint(acme.kit.address)\n',
    ],
)
def test_a_file_that_already_uses_the_new_name_is_refused(body: str) -> None:
    """Its own write of the new name would lack the ending, so two settings would be joined."""
    code, edits = tune(body)
    assert reasons(edits) == ["alias_collision"]
    assert "endpoint" in code


def test_the_new_name_is_not_a_legacy_finding_so_a_second_run_changes_nothing() -> None:
    once, _ = tune("acme.kit.endpoint = url\n")
    again, edits = tune(once)
    assert again == once
    assert edits == []


def test_the_scan_reports_the_setting_as_an_attribute_and_not_the_new_name() -> None:
    result = acme.scan(f'{HEADER}acme.kit.endpoint = "u"\nacme.kit.address = "u/"\n', kit.SPEC)
    assert [(f.line, f.kind, f.symbol) for f in result.findings] == [
        (3, "attribute", "acme.kit.endpoint")
    ]
