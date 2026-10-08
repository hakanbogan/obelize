"""`flag_only` on the fake `acme` SDK; it claims rows and every case gets its own source back.

`acme.FLAGGED` and `acme.GONE` split the three channels, so a rule reading the projection instead
of its own parameters claims every row in both; the Gemini changes' disjoint surfaces hide that.
"""

from __future__ import annotations

import acme

from obelize.models import Edit, Finding
from obelize.packs.schema import FlagOnlyChange, FlagOnlyParams
from obelize.transforms.kinds.flag_only import Guide, guides

HEADER = "import acme.sdk as sdk\n\nsdk.configure(key='k')\n"


def run(source: str, *changes: object) -> tuple[str, list[Edit]]:
    selected = changes or (acme.FLAGGED, acme.GONE)
    return acme.transform(source, *selected)  # type: ignore[arg-type]


def reported(edits: list[Edit]) -> list[tuple[int, str, str | None, str | None]]:
    return [(row.line, row.status, row.reason, row.rule_id) for row in edits]


def test_a_flagged_symbol_is_claimed_by_prefix() -> None:
    """The pack names a module and the finding names a class inside it."""
    source = f"{HEADER}\nSCHEMA = sdk.protos.Schema(kind='x')\n"
    produced, edits = run(source)
    assert produced == source
    assert reported(edits) == [(5, "needs_review", "flag_only_surface", "flag-protos")]


def test_a_removed_attribute_is_claimed_whole_and_is_unsupported() -> None:
    """`unsupported` is the scan's grade, passed through so the two halves cannot drift."""
    source = f"{HEADER}\ndef read():\n    m = sdk.Model('x')\n    s = m.chat()\n    return s.log\n"
    produced, edits = run(source)
    assert produced == source
    assert reported(edits) == [(8, "unsupported", "attribute_removed", "flag-session-log")]


def test_a_shape_is_claimed_on_the_reason_and_not_on_the_name() -> None:
    """`sys.modules[...]` has no reason of its own; it reports `dynamic_access` like the others."""
    source = (
        "import importlib\nimport sys\n\nfrom unittest import mock\n\n\n"
        "def fetched():\n    return importlib.import_module('acme.sdk')\n\n\n"
        "def stubbed(fake):\n    sys.modules['acme.sdk'] = fake\n\n\n"
        "def patched():\n    return mock.patch('acme.sdk.Model')\n"
    )
    produced, edits = run(source)
    assert produced == source
    assert reported(edits) == [
        (8, "needs_review", "flag_only_surface", "flag-protos"),
        (12, "needs_review", "flag_only_surface", "flag-protos"),
        (16, "needs_review", "flag_only_surface", "flag-protos"),
    ]


def test_a_change_claims_only_the_channels_it_declares() -> None:
    """A rule reading the projection would report each row twice, once under the wrong citation."""
    body = "def read():\n    m = sdk.Model('x')\n    s = m.chat()\n    return s.log, sdk.protos\n"
    source = f"{HEADER}\n{body}"
    _produced, flagged = run(source, acme.FLAGGED)
    _produced, gone = run(source, acme.GONE)
    assert [row.line for row in flagged] == [8]
    assert [row.line for row in gone] == [8]
    assert [row.reason for row in flagged] == ["flag_only_surface"]
    assert [row.reason for row in gone] == ["attribute_removed"]


def test_a_shape_is_not_claimed_by_a_change_that_declares_no_patterns() -> None:
    source = "from unittest import mock\n\nPATCH = mock.patch('acme.sdk.Model')\n"
    _produced, edits = run(source, acme.GONE)
    assert edits == []


def test_a_resolved_name_is_never_claimed_through_the_shape_channel() -> None:
    """Symbol and shape channels both name this `text_mention`; the finding's kind picks one."""
    source = "from unittest import mock\n\nPATCH = mock.patch('acme.sdk.protos.Schema')\n"
    _produced, edits = run(source, acme.FLAGGED)
    assert len(edits) == 1


def test_a_prose_mention_carries_no_bail_and_is_claimed_by_nothing() -> None:
    source = "NOTE = 'acme.sdk.protos is named here and imported nowhere'\n"
    produced, edits = run(source)
    assert produced == source
    assert edits == []


def test_a_row_another_rule_owns_is_left_to_it() -> None:
    """An ordinary legacy call is not this kind's, even in a refused file."""
    source = f"{HEADER}\nMODEL = sdk.Model('x')\n"
    _produced, edits = run(source)
    assert edits == []


def test_the_rule_consumes_no_symbol() -> None:
    """A refused surface keeps its import, or the run edits a file it otherwise refused."""
    from obelize.transforms.registry import rule_for

    rule = rule_for(acme.FLAGGED)
    assert rule is not None
    assert rule.consumes == frozenset()


def test_a_symbol_is_a_prefix_only_at_a_dot() -> None:
    """Called directly (the scan never yields it); must match `scan/analysis.py`'s prefix rule."""
    from obelize.transforms.registry import rule_for

    rule = rule_for(acme.FLAGGED)
    assert rule is not None
    assert rule.claims(_flagged("acme.sdk.protos"))
    assert rule.claims(_flagged("acme.sdk.protos.Schema"))
    assert not rule.claims(_flagged("acme.sdk.protoscope"))


def _flagged(symbol: str) -> Finding:
    return Finding(
        path="probe.py",
        line=1,
        column=0,
        kind="call",
        confidence_reason="alias_resolved",
        symbol=symbol,
        scan_status="needs_review",
        bail="flag_only_surface",
    )


def test_a_row_withheld_for_another_reason_is_not_claimed() -> None:
    """Called directly: `SCAN_VOCABULARY.md` section 6's ladder never stamps a flagged row wider."""
    from obelize.transforms.registry import rule_for

    rule = rule_for(acme.FLAGGED)
    assert rule is not None
    row = Finding(
        path="probe.py",
        line=1,
        column=0,
        kind="call",
        confidence_reason="alias_resolved",
        symbol="acme.sdk.protos",
        scan_status="needs_review",
        bail="module_alias_rebound",
    )
    assert not rule.claims(row)


def test_a_change_that_declares_only_the_stub_shape_claims_it() -> None:
    """Both packs declare all three shapes together, which hides what `sys_modules_stub` maps to."""
    change = FlagOnlyChange(
        id="flag-stub",
        kind="flag_only",
        citation="Acme migration notes, 'What did not move'",
        fixtures=("fixtures/negative/none.py", "fixtures/positive/one.before.py"),
        params=FlagOnlyParams(
            message="A stub under the legacy name replaces the module for every later importer.",
            suggestion="Patch the client object instead of the module path.",
            patterns=("sys_modules_stub",),
        ),
    )
    source = "import sys\n\n\ndef install(fake):\n    sys.modules['acme.sdk'] = fake\n"
    produced, edits = run(source, change)
    assert produced == source
    assert reported(edits) == [(5, "needs_review", "flag_only_surface", "flag-stub")]


BOTH = (
    f"{HEADER}\ndef read():\n    m = sdk.Model('x')\n    s = m.chat()\n"
    "    return s.log, sdk.protos\n"
)


def test_a_change_that_claimed_a_finding_gives_its_own_words_in_declared_order() -> None:
    expected = (
        Guide(
            f"{acme.PACK.id}:flag-protos",
            1,
            acme.FLAGGED.params.message,
            acme.FLAGGED.params.suggestion,
        ),
        Guide(
            f"{acme.PACK.id}:flag-session-log",
            1,
            acme.GONE.params.message,
            acme.GONE.params.suggestion,
        ),
    )
    assert guides(acme.PACK, acme.scan(BOTH).findings) == expected


def test_a_change_that_claimed_nothing_gives_nothing() -> None:
    """An ordinary legacy call is another rule's row, and the pack's words are not for it."""
    assert guides(acme.PACK, acme.scan(f"{HEADER}\nMODEL = sdk.Model('x')\n").findings) == ()


def test_a_guide_counts_every_finding_its_change_claimed() -> None:
    source = f"{HEADER}\nONE = sdk.protos.One()\nTWO = sdk.protos.Two()\n"
    (guide,) = guides(acme.PACK, acme.scan(source).findings)
    assert guide.findings == 2


def test_a_pack_with_no_flagged_change_gives_nothing() -> None:
    bare = acme.PACK.model_copy(update={"changes": (acme.CHANGE,)})
    assert guides(bare, acme.scan(BOTH).findings) == ()


def test_a_pack_speaks_only_for_its_own_changes() -> None:
    old = acme.scan("import acme.old as old\n\nREGISTRY = old.Registry()\n", acme.OLD_SPEC)
    both = [*acme.scan(BOTH).findings, *old.findings]
    assert [guide.rule_id for guide in guides(acme.OLD_PACK, both)] == [
        f"{acme.OLD_PACK.id}:flag-removed"
    ]
    assert [guide.rule_id for guide in guides(acme.PACK, both)] == [
        f"{acme.PACK.id}:flag-protos",
        f"{acme.PACK.id}:flag-session-log",
    ]
