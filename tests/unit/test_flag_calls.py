"""`flag_only.calls`: a name flagged for the calls that pass what changed, on `acme.calls`.

The pack is `tests/packs/generic/acme/calls-1-to-2`. `connect` lost `timeout` (its third positional
argument) and took `retries` and `secure` by keyword with new defaults, `Session` lost `verbose`,
and `drop` is gone, which has no entry in `calls` and is flagged wherever it is used.
"""

from __future__ import annotations

from pathlib import Path

import acme
import pytest

from obelize.models import CallShape, Finding, ScanSpec
from obelize.packs import loader
from obelize.packs.schema import FlagOnlyChange
from obelize.transforms.kinds.flag_only import FlagOnly, guides

PACK = Path(__file__).resolve().parents[1] / "packs" / "generic" / "acme" / "calls-1-to-2"
LOADED = loader.load(str(PACK / "pack.yaml"))
SPEC = loader.to_scan_spec(LOADED)
OWN = SPEC.model_copy(update={"shared": False})
HEAD = "import acme.calls\nfrom acme.calls import Session, connect, drop\n\n\n"
Row = tuple[int, str, str, str | None, str | None]


def found(source: str, spec: ScanSpec = SPEC) -> list[Row]:
    """Line, kind, symbol, bail and evidence of each use the scan reports in `source`."""
    return [
        (row.line - 4, row.kind, row.symbol or "", row.bail, row.evidence)
        for row in acme.scan(HEAD + source, spec).findings
        if row.line > 4 and row.scan_status != "not_a_usage"
    ]


def test_the_projection_keeps_every_flagged_symbol_and_the_shapes_of_some() -> None:
    assert SPEC.flag_only_symbols == ("acme.calls.Session", "acme.calls.connect", "acme.calls.drop")
    assert SPEC.flag_only_calls == {
        "acme.calls.Session": CallShape(keywords=("verbose",)),
        "acme.calls.connect": CallShape(
            keywords=("timeout",), positional_from=2, omits={"retries": 3, "secure": 4}
        ),
    }


@pytest.mark.parametrize(
    ("call", "evidence"),
    [
        ("connect(host, 1, 2, retries=1, secure=True)", "position 2"),
        ("connect(host, 1, retries=1, secure=True, timeout=3)", "keyword timeout"),
        ("acme.calls.connect(host, 1, secure=True)", "omitted retries"),
        ("connect(host, 1, retries=1)", "omitted secure"),
        ("connect(host, 1)", "omitted retries"),
        ("connect(*rest)", "spread"),
        ("connect(host, 1, **rest)", "spread"),
        ("connect(host, 1, retries=1, secure=True, *rest)", "spread"),
        ("Session(verbose=True)", "keyword verbose"),
    ],
)
def test_a_call_that_passes_what_changed_is_a_row_that_says_so(call: str, evidence: str) -> None:
    ((_, kind, _, bail, says),) = found(f"def run(host, rest):\n    {call}\n")
    assert (kind, bail, says) == ("call", "flag_only_surface", evidence)


@pytest.mark.parametrize(
    "call",
    [
        "connect(host, 1, retries=1, secure=True)",
        "acme.calls.connect(host, port=1, retries=1, secure=True)",
        "Session()",
        "Session(host)",
        "Session(host, 1, 2, 3)",
    ],
)
def test_a_call_that_passes_none_of_it_is_no_row_in_a_pack_that_shares_its_module(
    call: str,
) -> None:
    assert found(f"def run(host):\n    {call}\n") == []


def test_in_a_pack_that_does_not_share_its_module_that_call_is_graded_as_if_not_flagged() -> None:
    rows = acme.scan(HEAD + "def run(host):\n    connect(host, 1, retries=1, secure=True)\n", OWN)
    statuses = [(row.kind, row.symbol, row.scan_status, row.bail) for row in rows.findings]
    assert ("call", "acme.calls.connect", "eligible", None) in statuses
    assert all(row.scan_status == "eligible" for row in rows.findings)


@pytest.mark.parametrize(
    "use",
    [
        "map(connect, hosts)",
        "isinstance(host, Session)",
        "register(handler=acme.calls.connect)",
    ],
)
def test_a_name_handed_to_a_call_is_not_flagged_for_its_signature(use: str) -> None:
    source = f"def run(host, hosts):\n    return {use}\n"
    assert found(source) == []


def test_a_name_that_is_annotated_is_not_flagged_either() -> None:
    source = (
        "def run(a: Session, b: 'acme.calls.Session', c: list[Session] = []) -> Session:\n"
        "    d: acme.calls.Session = a\n    return d\n"
    )
    assert found(source) == []


def test_an_import_of_a_name_flagged_for_some_calls_is_no_row() -> None:
    assert (
        acme.scan("import acme.calls\nfrom acme.calls import Session, connect\n", SPEC).findings
        == ()
    )


@pytest.mark.parametrize(
    "use",
    [
        "class Pool(Session):\n    pass\n",
        "dial = acme.calls.connect\n",
        "ready = [connect, Session]\n",
        "def run(maker=connect):\n    return maker\n",
        "@connect\ndef run():\n    pass\n",
    ],
)
def test_a_name_used_any_other_way_is_a_row_as_it_was_for_a_call_to_come(use: str) -> None:
    rows = found(use)
    assert rows
    assert {(row[3], row[4]) for row in rows} == {("flag_only_surface", None)}


def test_a_name_below_a_flagged_one_is_flagged_wherever_it_is_used() -> None:
    (row,) = found("def run():\n    return Session.fresh(1)\n")
    assert row == (2, "call", "acme.calls.Session.fresh", "flag_only_surface", None)


def test_a_name_only_a_keyword_can_give_is_left_out_by_any_number_of_positional_arguments() -> None:
    strict = SPEC.model_copy(
        update={"flag_only_calls": {"acme.calls.connect": CallShape(omits={"strict": None})}}
    )
    rows = found(
        "def run(host):\n    connect(host, 1, 2, 3, 4)\n    connect(host, strict=1)\n", strict
    )
    assert [(row[0], row[4]) for row in rows] == [(2, "omitted strict")]


def test_a_shape_does_not_hold_under_a_name_flagged_whole() -> None:
    pool = "acme.calls.pool"
    both = SPEC.model_copy(
        update={
            "symbols": (*SPEC.symbols, pool, f"{pool}.open"),
            "flag_only_symbols": (*SPEC.flag_only_symbols, pool, f"{pool}.open"),
            "flag_only_calls": {**SPEC.flag_only_calls, f"{pool}.open": CallShape(keywords=("x",))},
        }
    )
    rows = found("def run():\n    return acme.calls.pool.open(1)\n", both)
    assert rows == [(2, "call", f"{pool}.open", "flag_only_surface", None)]


def test_a_name_with_no_entry_in_calls_is_flagged_wherever_it_is_used() -> None:
    rows = found("def run(handle, items):\n    drop(handle)\n    return map(drop, items)\n")
    assert [(row[2], row[3], row[4]) for row in rows] == [
        ("acme.calls.drop", "flag_only_surface", None)
    ] * 2


def test_an_import_inside_a_function_keeps_the_row_it_always_had() -> None:
    rows = acme.scan("def run():\n    from acme.calls import connect\n    return connect\n", SPEC)
    assert [(row.kind, row.bail) for row in rows.findings if row.kind == "import"] == [
        ("import", "flag_only_surface")
    ]


def test_the_change_claims_the_rows_for_its_calls_and_says_why_once() -> None:
    signatures = LOADED.pack.changes[0]
    assert isinstance(signatures, FlagOnlyChange)
    source = (
        "def run(host):\n    return connect(host, 1, 2), Session(verbose=1), connect(host, 1)\n"
    )
    rows = acme.scan("from acme.calls import Session, connect\n\n\n" + source, SPEC).findings
    assert [FlagOnly(signatures).claims(row) for row in rows] == [True] * 3
    (guide,) = guides(LOADED.pack, rows)
    assert (guide.rule_id, guide.findings) == ("acme/calls-1-to-2:flag-signatures", 3)
    assert "keyword-only" in guide.message


def test_a_finding_carries_the_evidence_through_its_document() -> None:
    (row,) = (r for r in acme.scan(HEAD + "connect(1, 2, 3)\n", SPEC).findings if r.evidence)
    assert Finding.model_validate_json(row.model_dump_json()) == row
