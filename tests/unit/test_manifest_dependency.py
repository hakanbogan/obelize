"""`manifest_dependency` on the fake `acme.PIN`, with the repository given as a `Migration` value.

Each refused shape is paired with the one it must not refuse: a guard that fires on everything
is not a guard.
"""

from __future__ import annotations

import acme
import pytest

from obelize.models import Edit, Finding, ManifestPlan
from obelize.packs.schema import ManifestDependencyChange, ManifestDependencyParams
from obelize.scan.manifests import Migration
from obelize.transforms import manifest as manifest_rules
from obelize.transforms.registry import manifest_rule_for

# The four repository states ADR-010 F-2 distinguishes.
CLEAR = Migration(migrated=("app.py",))
BLOCKED = Migration(migrated=("app.py",), blocking=("legacy.py",))
STALLED = Migration(blocking=("legacy.py",))
DORMANT = Migration()


def reported(edits: list[Edit]) -> list[tuple[int, str, str | None]]:
    return [(row.line, row.status, row.reason) for row in edits]


def test_both_halves_clear_replaces_the_declaration() -> None:
    produced, edits = acme.declared("requirements.txt", "acme-sdk==1.2.3\nhttpx>=0.27\n", CLEAR)
    assert produced == "acme-client>=2\nhttpx>=0.27\n"
    assert reported(edits) == [(1, "auto", None)]


def test_a_pin_with_no_version_gains_one() -> None:
    """The version span is empty rather than absent, so the pack's version has a place to go."""
    produced, _edits = acme.declared("requirements.txt", "acme-sdk\n", CLEAR)
    assert produced == "acme-client>=2\n"


def test_an_environment_marker_stays_where_the_author_put_it() -> None:
    """A marker says when the requirement applies, not what it is, so unlike an extra it stays."""
    source = 'acme-sdk == 1.2.3 ; python_version < "3.12"\n'
    produced, _edits = acme.declared("requirements.txt", source, CLEAR)
    assert produced == 'acme-client>=2 ; python_version < "3.12"\n'


def test_two_declarations_on_one_line_are_both_replaced() -> None:
    """Right to left, so the first one's columns still mean what they meant."""
    source = '[project]\ndependencies = ["acme-sdk==1", "acme-sdk==1.2"]\n'
    produced, edits = acme.declared("pyproject.toml", source, CLEAR)
    assert produced == '[project]\ndependencies = ["acme-client>=2", "acme-client>=2"]\n'
    assert reported(edits) == [(2, "auto", None), (2, "auto", None)]


def test_a_table_key_keeps_its_spacing_and_its_quote() -> None:
    source = "[packages]\nacme-sdk   =   '==1.2.3'\n"
    produced, _edits = acme.declared("Pipfile", source, CLEAR)
    assert produced == "[packages]\nacme-client   =   '>=2'\n"


def test_a_blocked_removal_adds_the_new_pin_and_keeps_the_legacy_one() -> None:
    produced, edits = acme.declared("requirements.txt", "acme-sdk==1.2.3\nhttpx>=0.27\n", BLOCKED)
    assert produced == "acme-sdk==1.2.3\nacme-client>=2\nhttpx>=0.27\n"
    assert reported(edits) == [
        (1, "auto", None),
        (1, "needs_review", "repo_not_fully_migrated"),
    ]


def test_the_added_line_is_the_legacy_line_with_the_declaration_swapped() -> None:
    """So all five layouts are written without naming any of them."""
    source = "[options]\ninstall_requires =\n    acme-sdk==1.2.3\n"
    produced, _edits = acme.declared("setup.cfg", source, BLOCKED)
    assert produced == "[options]\ninstall_requires =\n    acme-sdk==1.2.3\n    acme-client>=2\n"


def test_nothing_is_added_where_the_new_distribution_is_already_declared() -> None:
    """F-2's first half has nothing to do, so the reader emits no row for it."""
    source = "acme-sdk==1.2.3\nacme-client>=2\n"
    produced, edits = acme.declared("requirements.txt", source, BLOCKED)
    assert produced == source
    assert reported(edits) == [(1, "needs_review", "repo_not_fully_migrated")]


@pytest.mark.parametrize(
    ("what", "line"),
    [
        ("extras", "acme-sdk[grpc]==1.2.3\n"),
        ("a direct url", "acme-sdk @ https://example.invalid/acme_sdk-1.2.3.whl\n"),
    ],
)
def test_a_requirement_that_says_more_than_a_pin_is_refused(what: str, line: str) -> None:
    """An extra lives in the old distribution's namespace and a URL names its file."""
    produced, edits = acme.declared("requirements.txt", line, CLEAR)
    assert produced == line, what
    assert reported(edits) == [(1, "needs_review", "manifest_pin_shape_unsupported")], what


def test_a_table_value_that_is_not_a_version_string_is_refused() -> None:
    source = '[packages]\nacme-sdk = {version = "==1.2.3", extras = ["grpc"]}\n'
    produced, edits = acme.declared("Pipfile", source, CLEAR)
    assert produced == source
    assert reported(edits) == [(2, "needs_review", "manifest_pin_shape_unsupported")]


def test_a_table_value_that_is_a_version_string_is_not() -> None:
    source = '[packages]\nacme-sdk = "==1.2.3"\n'
    produced, _edits = acme.declared("Pipfile", source, CLEAR)
    assert produced == '[packages]\nacme-client = ">=2"\n'


def test_a_setup_py_literal_whose_bytes_are_not_its_value_is_refused() -> None:
    """An escape makes span and value lengths differ: the declaration stands but has no address."""
    source = 'from setuptools import setup\n\nsetup(install_requires=["acme\\u002dsdk==1.2.3"])\n'
    produced, edits = acme.declared("setup.py", source, CLEAR)
    assert produced == source
    assert reported(edits) == [(3, "needs_review", "manifest_pin_shape_unsupported")]


def test_a_setup_py_literal_that_runs_over_two_lines_is_refused() -> None:
    """Only an escaped newline can reach the rule: PEP 508 rejects a real one."""
    source = 'from setuptools import setup\n\nsetup(install_requires=["acme-sdk\\\n==1.2.3"])\n'
    produced, edits = acme.declared("setup.py", source, CLEAR)
    assert produced == source
    assert reported(edits) == [(3, "needs_review", "manifest_pin_shape_unsupported")]


def test_a_plain_setup_py_literal_is_rewritten() -> None:
    source = 'from setuptools import setup\n\nsetup(install_requires=["acme-sdk==1.2.3"])\n'
    produced, _edits = acme.declared("setup.py", source, CLEAR)
    expected = 'from setuptools import setup\n\nsetup(install_requires=["acme-client>=2"])\n'
    assert produced == expected


def test_a_declaration_sharing_its_line_with_a_key_is_not_copied() -> None:
    source = '[project]\ndependencies = ["acme-sdk==1.2.3"]\n'
    produced, edits = acme.declared("pyproject.toml", source, BLOCKED)
    assert produced == source
    assert reported(edits) == [
        (2, "needs_review", "manifest_pin_shape_unsupported"),
        (2, "needs_review", "repo_not_fully_migrated"),
    ]


def test_the_same_line_is_replaced_when_nothing_is_blocking() -> None:
    """The key blocks a copy of the line, not a splice within it."""
    source = '[project]\ndependencies = ["acme-sdk==1.2.3"]\n'
    produced, edits = acme.declared("pyproject.toml", source, CLEAR)
    assert produced == '[project]\ndependencies = ["acme-client>=2"]\n'
    assert reported(edits) == [(2, "auto", None)]


def test_a_declaration_sharing_its_line_with_another_is_not_copied() -> None:
    """A copy of the line would declare `httpx` twice."""
    source = '[project]\ndependencies = [\n  "acme-sdk==1.2.3", "httpx>=0.27",\n]\n'
    produced, edits = acme.declared("pyproject.toml", source, BLOCKED)
    assert produced == source
    assert reported(edits) == [
        (3, "needs_review", "manifest_pin_shape_unsupported"),
        (3, "needs_review", "repo_not_fully_migrated"),
    ]


def test_a_declaration_alone_on_a_continuation_line_is_copied() -> None:
    source = '[project]\ndependencies = [\n  "acme-sdk==1.2.3",\n  "httpx>=0.27",\n]\n'
    produced, _edits = acme.declared("pyproject.toml", source, BLOCKED)
    assert produced == (
        '[project]\ndependencies = [\n  "acme-sdk==1.2.3",\n  "acme-client>=2",\n'
        '  "httpx>=0.27",\n]\n'
    )


def test_a_pin_nothing_uses_is_context_and_not_an_edit() -> None:
    """Nothing migrated or imports it; removing it would tidy a manifest for an unmade migration."""
    produced, edits = acme.declared("requirements.txt", "acme-sdk==1.2.3\n", DORMANT)
    assert produced == "acme-sdk==1.2.3\n"
    assert edits == []


def test_a_pin_in_a_repository_that_migrated_nothing_is_withheld() -> None:
    produced, edits = acme.declared("requirements.txt", "acme-sdk==1.2.3\n", STALLED)
    assert produced == "acme-sdk==1.2.3\n"
    assert reported(edits) == [(1, "needs_review", "repo_not_fully_migrated")]


def test_the_new_distribution_declared_over_legacy_code_is_reported() -> None:
    produced, edits = acme.declared("requirements.txt", "acme-client>=2\n", STALLED)
    assert produced == "acme-client>=2\n"
    assert reported(edits) == [(1, "needs_review", "manifest_code_mismatch")]


def test_a_manifest_nothing_touched_is_the_bytes_it_arrived_as() -> None:
    """The same object, not a re-encoding."""
    data = b"acme-sdk==1.2.3\n"
    context = manifest_rules.ManifestContext.build("requirements.txt", data, _empty())
    assert manifest_rules.finish(context) is data


def test_a_crlf_manifest_keeps_its_terminators_on_the_line_that_is_added() -> None:
    """The added line is the legacy line with two spans swapped, so it keeps the `\\r`."""
    source = "acme-sdk==1.2.3\r\nhttpx>=0.27\r\n"
    produced, _edits = acme.declared("requirements.txt", source, BLOCKED)
    assert produced == "acme-sdk==1.2.3\r\nacme-client>=2\r\nhttpx>=0.27\r\n"


def test_a_manifest_with_no_trailing_newline_does_not_gain_one() -> None:
    produced, _edits = acme.declared("requirements.txt", "acme-sdk==1.2.3", CLEAR)
    assert produced == "acme-client>=2"


def test_the_rule_claims_manifest_rows_about_either_side_and_nothing_else() -> None:
    rule = manifest_rule_for(acme.PIN)
    assert rule is not None
    assert rule.claims(_manifest_row("acme-sdk"))
    assert rule.claims(_manifest_row("Acme_SDK")), "PEP 503 folds, so the spelling is not the name"
    assert rule.claims(_manifest_row("acme-client"))
    assert not rule.claims(_manifest_row("httpx"))
    assert not rule.claims(
        Finding(
            path="app.py",
            line=1,
            column=0,
            kind="import",
            confidence_reason="alias_resolved",
            symbol="acme.sdk",
            scan_status="eligible",
        )
    )


def _manifest_row(symbol: str) -> Finding:
    return Finding(
        path="requirements.txt",
        line=1,
        column=0,
        kind="manifest",
        confidence_reason="manifest_dependency",
        symbol=symbol,
        scan_status="eligible",
    )


def _empty() -> ManifestPlan:
    return ManifestPlan()


def test_the_spelling_written_is_the_pack_s_and_not_the_canonical_form() -> None:
    """PEP 503 folding is for comparison; every pack in the tree spells canonically, hiding this."""
    change = ManifestDependencyChange(
        id="pin",
        kind="manifest_dependency",
        citation="Acme migration notes, 'Installing'",
        fixtures=("fixtures/negative/none.txt", "fixtures/positive/one.before.txt"),
        params=ManifestDependencyParams(from_name="acme-sdk", to_name="Acme_Client", to_spec=">=2"),
    )
    produced, _edits = acme.declared("requirements.txt", "acme-sdk==1.2.3\n", CLEAR, change=change)
    assert produced == "Acme_Client>=2\n"


def test_a_quoted_table_key_is_addressed_inside_its_quotes() -> None:
    """An address one column left would overwrite the opening quote and strand the closing one."""
    source = '[packages]\n"acme-sdk" = "==1.2.3"\n'
    produced, _edits = acme.declared("Pipfile", source, CLEAR)
    assert produced == '[packages]\n"acme-client" = ">=2"\n'


@pytest.mark.parametrize(
    ("what", "line"),
    [
        ("a key with no value at all", "acme-sdk =\n"),
        ("a value that is not a string", "acme-sdk = 11\n"),
        ("a quote nothing closes", 'acme-sdk = "==1.2.3\n'),
    ],
)
def test_a_table_value_that_is_not_one_quoted_string_is_refused(what: str, line: str) -> None:
    """The reader works in lines, not through a parser, so even invalid TOML must come out whole."""
    source = f"[packages]\n{line}"
    produced, edits = acme.declared("Pipfile", source, CLEAR)
    assert produced == source, what
    assert reported(edits) == [(2, "needs_review", "manifest_pin_shape_unsupported")], what
