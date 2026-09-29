"""The codemod driver, one question at a time, on repositories built from the fake `acme` SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import acme
import libcst as cst
import pytest

from obelize.models import Config, Edit, ImpactPolicy
from obelize.scan import parse, runner
from obelize.transforms import codemod, registry

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from pathlib import Path

    from obelize.models import Finding
    from obelize.packs.schema import Change, ChangeKind
    from obelize.transforms.base import RuleContext

# Migrates whole: an import, a client, a model and a call.
CLEAN = '''"""A module with nothing wrong in it."""

import acme.sdk as sdk

sdk.configure(key="k")

M = sdk.Model("m")


def go(text):
    return M.run(text).words
'''

# A constructor keyword the scan grades `eligible` and `generative_model_calls` refuses.
REFUSES = CLEAN.replace('sdk.Model("m")', 'sdk.Model("m", nonsense=1)')

# A free function referenced, not called: its change is for a call, so no rule claims the row.
UNCLAIMED = '''"""A reference no rule claims."""

import acme.sdk as sdk

sdk.configure(key="k")

PROBE = sdk.measure
'''

MANIFEST = "acme-sdk==0.1.0\n"


def test_a_repository_with_nothing_wrong_in_it_is_written_whole(tmp_path: Path) -> None:
    run = acme.repository(tmp_path, {"app.py": CLEAN, "requirements.txt": MANIFEST})
    assert [outcome.path for outcome in run.written] == ["app.py", "requirements.txt"]
    assert all(row.status == "auto" for row in run.edits), run.edits
    assert run.manifest_plan.blocking == ()
    assert run.manifests[0].after.decode() == "acme-client>=2\n"


def test_one_bailing_usage_leaves_the_file_byte_identical(tmp_path: Path) -> None:
    """ADR-010 F-1: the other rules' bytes are discarded and their ready rows cite the refusal."""
    run = acme.repository(tmp_path, {"app.py": REFUSES, "requirements.txt": MANIFEST})
    outcome = run.files[0]
    assert outcome.after == outcome.before
    assert not outcome.written
    assert [(row.line, row.status, row.reason, row.caused_by) for row in outcome.edits] == [
        (3, "needs_review", "file_not_fully_migrated", ("unknown_ctor_kwarg",)),
        (5, "needs_review", "file_not_fully_migrated", ("unknown_ctor_kwarg",)),
        (7, "needs_review", "unknown_ctor_kwarg", None),
        (11, "needs_review", "unknown_ctor_kwarg", None),
    ]


def test_the_refused_file_is_still_in_the_plan_the_manifest_pass_reads(tmp_path: Path) -> None:
    """The manifest pass runs after the rules: the scan alone would drop the pin `bad.py` keeps."""
    run = acme.repository(
        tmp_path, {"good.py": CLEAN, "bad.py": REFUSES, "requirements.txt": MANIFEST}
    )
    assert run.manifest_plan.blocking == ("bad.py",)
    assert run.manifests[0].after.decode() == "acme-sdk==0.1.0\nacme-client>=2\n"
    assert [outcome.path for outcome in run.written] == ["good.py", "requirements.txt"]


# `configure` sets a process-wide default: a module left on the legacy SDK with no `configure` of
# its own runs on another module's, so that module's file is withheld (ADR-031 D11).

# Holds the `configure`, with nothing of its own to refuse.
CONFIGURES = '''"""The one `configure`."""

import acme.sdk as sdk

sdk.configure(key="k")
'''

# No `configure` of its own, so its calls stay on the legacy SDK.
RELIES = '''"""Calls that run on another module's `configure`."""

import acme.sdk as sdk

M = sdk.Model("m")


def go(text):
    return M.run(text).words
'''


def test_a_configure_another_module_still_runs_on_withholds_its_file(tmp_path: Path) -> None:
    run = acme.repository(
        tmp_path, {"settings.py": CONFIGURES, "use.py": RELIES, "requirements.txt": MANIFEST}
    )
    assert run.written == ()
    held = next(outcome for outcome in run.files if outcome.path == "settings.py")
    assert [(row.line, row.status, row.reason, row.caused_by) for row in held.edits] == [
        (3, "needs_review", "file_not_fully_migrated", ("configure_consumed_elsewhere",)),
        (5, "needs_review", "configure_consumed_elsewhere", None),
    ]
    rows = [row for row in run.findings if str(row.path) == "settings.py"]
    assert [(row.line, row.bail, row.caused_by) for row in rows] == [
        (3, "file_not_fully_migrated", ("configure_consumed_elsewhere",)),
        (5, "configure_consumed_elsewhere", None),
    ]
    assert run.manifest_plan.blocking == ("settings.py", "use.py")


def test_a_module_the_rules_leave_on_the_legacy_sdk_holds_the_configure_too(
    tmp_path: Path,
) -> None:
    """The scan cannot see `measure` needs a client; the rule refuses, so `use.py` stays legacy."""
    used = (
        '"""A free function, and no `configure`."""\n\n'
        'import acme.sdk as sdk\n\nV = sdk.measure("k", "b")\n'
    )
    run = acme.repository(tmp_path, {"settings.py": CONFIGURES, "use.py": used})
    scanned = runner.scan(tmp_path, Config(), acme.SPEC, jobs=1)
    plan = next(result.plan for result in scanned.results if result.path == "use.py")
    assert {row.scan_status for row in plan.findings} == {"eligible"}
    assert run.written == ()


def test_a_module_left_out_of_the_run_still_runs_on_the_configure(tmp_path: Path) -> None:
    run = acme.repository(
        tmp_path,
        {"settings.py": CONFIGURES, "use.py": RELIES},
        sources={"settings.py": CONFIGURES.encode()},
    )
    assert run.written == ()


# Migrates whole with no client: the import is all it has.
BARE = '"""An import and nothing else."""\n\nimport acme.sdk as sdk\n'


def test_a_module_the_run_migrates_as_well_holds_nothing_back(tmp_path: Path) -> None:
    """`bare.py` has no `configure`, but the run takes it off the legacy SDK too."""
    run = acme.repository(tmp_path, {"app.py": CLEAN, "bare.py": BARE})
    assert [outcome.path for outcome in run.written] == ["app.py", "bare.py"]


def test_only_a_file_that_holds_a_configure_is_withheld(tmp_path: Path) -> None:
    """`bare.py` does not call the API, so nothing it does needs a default."""
    run = acme.repository(tmp_path, {"settings.py": CONFIGURES, "use.py": RELIES, "bare.py": BARE})
    assert [outcome.path for outcome in run.written] == ["bare.py"]


def test_a_configure_already_withheld_keeps_the_code_that_withheld_it(tmp_path: Path) -> None:
    """A file's own defect, not `configure_consumed_elsewhere`, is its reason."""
    run = acme.repository(tmp_path, {"bad.py": REFUSES, "use.py": RELIES})
    rows = [row for row in run.findings if str(row.path) == "bad.py" and row.line == 5]
    assert [(row.bail, row.caused_by) for row in rows] == [
        ("file_not_fully_migrated", ("unknown_ctor_kwarg",))
    ]


def test_a_test_that_patches_the_sdk_by_name_holds_nothing_back(tmp_path: Path) -> None:
    """A patch target imports the module (F-2 keeps the pin) but never calls the API."""
    patched = 'from unittest import mock\n\nPATCH = mock.patch("acme.sdk.Model")\n'
    run = acme.repository(tmp_path, {"app.py": CLEAN, "test_app.py": patched})
    assert run.manifest_plan.blocking == ("test_app.py",)
    assert [outcome.path for outcome in run.written] == ["app.py"]


def test_a_row_no_rule_claims_withholds_the_file(tmp_path: Path) -> None:
    """F-1's other half; `usage_unmapped` comes from the driver, not a rule."""
    run = acme.repository(tmp_path, {"app.py": UNCLAIMED, "requirements.txt": MANIFEST})
    outcome = run.files[0]
    assert not outcome.written
    assert [(row.line, row.reason, row.rule_id) for row in outcome.edits] == [
        (3, "file_not_fully_migrated", "rename-import"),
        (5, "file_not_fully_migrated", "configure-to-client"),
        (7, "usage_unmapped", None),
    ]


def test_the_row_the_driver_reports_names_no_rule(tmp_path: Path) -> None:
    """No rule claimed it; `Edit` allows a missing `rule_id` only on a withheld row."""
    run = acme.repository(tmp_path, {"app.py": UNCLAIMED})
    unclaimed = [row for row in run.edits if row.reason == codemod.UNCLAIMED]
    assert [row.rule_id for row in unclaimed] == [None]


def test_nothing_migrated_leaves_the_manifest_exactly_as_it_was(tmp_path: Path) -> None:
    """F-2's fourth state, reached because the rules, not the scan, refused the file."""
    run = acme.repository(tmp_path, {"app.py": UNCLAIMED, "requirements.txt": MANIFEST})
    manifest = run.manifests[0]
    assert manifest.after == manifest.before
    assert [row.reason for row in manifest.edits] == ["repo_not_fully_migrated"]


def test_a_repository_with_no_manifest_has_no_manifest_outcome(tmp_path: Path) -> None:
    run = acme.repository(tmp_path, {"app.py": CLEAN})
    assert run.manifests == ()
    assert run.manifest_plan.findings == ()
    assert [outcome.path for outcome in run.written] == ["app.py"]


def test_a_row_the_scan_withheld_keeps_the_status_the_scan_gave_it(tmp_path: Path) -> None:
    """Refusals land only on ready rows: the scan's `unsupported` `S.log` keeps its grade."""
    source = '''"""A removed attribute, which the scan already refused."""

import acme.sdk as sdk

sdk.configure(key="k")

M = sdk.Model("m")
S = M.chat()
TRACE = S.log
'''
    run = acme.repository(tmp_path, {"app.py": source})
    assert [
        (row.line, row.scan_status, row.bail, row.caused_by) for row in run.plans[0].findings
    ] == [
        (3, "needs_review", "file_not_fully_migrated", ("attribute_removed",)),
        (5, "needs_review", "file_not_fully_migrated", ("attribute_removed",)),
        (7, "needs_review", "file_not_fully_migrated", ("attribute_removed",)),
        (8, "needs_review", "file_not_fully_migrated", ("attribute_removed",)),
        (9, "unsupported", "attribute_removed", None),
    ]


def test_a_refusal_names_the_row_it_is_about_and_not_the_line(tmp_path: Path) -> None:
    """`Edit` carries no column, so the reporting rule, not the line, says which row it refused."""
    source = '''"""Two rules on one line."""

import acme.sdk as sdk

sdk.configure(key="k"); M = sdk.Model("m", nonsense=1)


def go(text):
    return M.run(text).words
'''
    run = acme.repository(tmp_path, {"app.py": source})
    assert [(row.line, row.column, row.bail) for row in run.plans[0].findings] == [
        (3, 0, "file_not_fully_migrated"),
        (5, 0, "file_not_fully_migrated"),
        (5, 28, "unknown_ctor_kwarg"),
        (9, 11, "unknown_ctor_kwarg"),
    ]


def test_the_order_the_pack_declares_is_the_order_a_run_uses(tmp_path: Path) -> None:
    assert [rule.kind for rule in registry.rules(acme.PACK)] == [
        "rename_import",
        "configure_to_client",
        "generative_model_calls",
        "rewrite_call",
        "rewrite_call",
        "flag_only",
        "flag_only",
    ]
    run = acme.repository(tmp_path, {"app.py": CLEAN})
    assert run.files[0].written


def test_the_order_is_a_dependency_and_a_pack_that_inverts_it_refuses(tmp_path: Path) -> None:
    """Inverted, the client's alias collides; the file is withheld, not renamed (ADR-026 D6)."""
    inverted = acme.PACK.model_copy(
        update={
            "changes": (
                acme.CLIENT,
                acme.CHANGE,
                acme.MODEL,
                acme.MEASURE,
                acme.LOOKUP,
                acme.FLAGGED,
                acme.GONE,
                acme.PIN,
            )
        }
    )
    run = acme.repository(tmp_path, {"app.py": CLEAN}, pack=inverted)
    assert not run.files[0].written
    assert {row.reason for row in run.files[0].edits} == {
        "alias_collision",
        "file_not_fully_migrated",
    }


def test_no_two_rules_claim_one_row(tmp_path: Path) -> None:
    """`_refusals` relies on it: a row claimed twice would be refused under two citations."""
    source = '''"""Every channel at once."""

import acme.sdk as sdk
from unittest import mock

sdk.configure(key="k")

M = sdk.Model("m")
S = M.chat()
PATCH = mock.patch("acme.sdk.protos.Shape")
LOG = S.log
PROBE = sdk.measure


def go(text):
    return M.run(text).words
'''
    run = acme.repository(tmp_path, {"app.py": source})
    rules = registry.rules(acme.PACK)
    claimed = [
        (finding.line, [rule.kind for rule in rules if rule.claims(finding)])
        for finding in run.plans[0].findings
    ]
    assert claimed, "the corpus for this invariant has to have rows in it"
    assert [(line, who) for line, who in claimed if len(who) > 1] == []


class _Yields:
    """Replaces the docstring with `(yield)`, which libcst parses and `compile()` refuses.

    It claims no row, so only the bytes change; no real rule can be made to write such bytes.
    """

    kind: ClassVar[ChangeKind] = "flag_only"

    def __init__(self, change: Change) -> None:
        self._id = change.id

    @property
    def consumes(self) -> frozenset[str]:
        return frozenset()

    @property
    def client_readers(self) -> frozenset[str]:
        return frozenset()

    def claims(self, finding: Finding) -> bool:
        return False

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        found = _FirstString()
        context.module.visit(found)
        assert found.node is not None, "the fixture for this rule needs a docstring"
        context.rewrites.set(found.node, cst.parse_expression("(yield)"))
        return ()


class _FirstString(cst.CSTVisitor):
    """The first `SimpleString` in document order, by identity."""

    def __init__(self) -> None:
        self.node: cst.SimpleString | None = None

    def visit_SimpleString(  # noqa: N802 - libcst dispatches by name
        self, node: cst.SimpleString
    ) -> None:
        if self.node is None:
            self.node = node


@pytest.fixture
def breaking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry.RULES, "flag_only", _Yields)


@pytest.mark.usefixtures("breaking")
def test_the_output_gates_withhold_every_row_of_the_file(tmp_path: Path) -> None:
    """No `caused_by`: when the bytes are rejected, no row survived to be a cause."""
    run = acme.repository(tmp_path, {"app.py": CLEAN})
    outcome = run.files[0]
    assert outcome.after == outcome.before
    assert {(row.status, row.reason, row.caused_by) for row in outcome.edits} == {
        ("needs_review", "output_does_not_parse", None)
    }
    assert {row.bail for row in run.plans[0].findings} == {"output_does_not_parse"}


@pytest.mark.usefixtures("breaking")
def test_the_gate_is_asked_only_of_a_file_this_run_would_write(tmp_path: Path) -> None:
    """A refused file's bytes are discarded ungated, so the refusal stays the reason."""
    run = acme.repository(tmp_path, {"app.py": REFUSES})
    reasons = {row.reason for row in run.files[0].edits}
    assert "output_does_not_parse" not in reasons
    assert reasons == {"unknown_ctor_kwarg", "file_not_fully_migrated"}


# `compile()` accepts reading an unbound name (a runtime NameError), so a second gate checks it.


class _Dangles(_Yields):
    """As `_Yields`, but the docstring becomes a name nothing binds."""

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        found = _FirstString()
        context.module.visit(found)
        assert found.node is not None, "the fixture for this rule needs a docstring"
        context.rewrites.set(found.node, cst.parse_expression("client_nobody_bound"))
        return ()


class _Binds(_Yields):
    """The control: reads the migrated client name `handle`, inside a `lambda`.

    At module level the read would precede the binding, a NameError the gate also refuses.
    """

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        found = _FirstString()
        context.module.visit(found)
        assert found.node is not None, "the fixture for this rule needs a docstring"
        context.rewrites.set(found.node, cst.parse_expression("lambda: handle"))
        return ()


def test_a_name_nothing_binds_withholds_every_row_of_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(registry.RULES, "flag_only", _Dangles)
    run = acme.repository(tmp_path, {"app.py": CLEAN})
    outcome = run.files[0]
    assert outcome.after == outcome.before
    assert {(row.status, row.reason, row.caused_by) for row in outcome.edits} == {
        ("needs_review", "output_names_unresolved", None)
    }
    assert {row.bail for row in run.plans[0].findings} == {"output_names_unresolved"}


def test_a_name_the_input_already_left_unbound_is_not_the_rule_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Judged against the input, so a name it already leaves unbound (star import) is allowed."""
    monkeypatch.setitem(registry.RULES, "flag_only", _Dangles)
    source = CLEAN + "\n\nPROBE = client_nobody_bound\n"
    run = acme.repository(tmp_path, {"app.py": source})
    assert [outcome.path for outcome in run.written] == ["app.py"]


def test_a_name_the_output_binds_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(registry.RULES, "flag_only", _Binds)
    run = acme.repository(tmp_path, {"app.py": CLEAN})
    assert [outcome.path for outcome in run.written] == ["app.py"]
    assert run.files[0].after.startswith(b"lambda: handle\n")


def test_a_file_with_an_eligible_row_and_no_bytes_is_refused(tmp_path: Path) -> None:
    """Otherwise F-2 reports a migration that nothing performed."""
    with pytest.raises(codemod.CodemodError, match="eligible findings"):
        acme.repository(
            tmp_path,
            {"app.py": CLEAN, "requirements.txt": MANIFEST},
            sources={"requirements.txt": MANIFEST.encode("utf-8")},
        )


def test_a_path_no_scan_looked_at_is_refused(tmp_path: Path) -> None:
    """A plan grades the bytes it read, so there is nothing to grade this against."""
    with pytest.raises(codemod.CodemodError, match="were not in this scan"):
        acme.repository(
            tmp_path,
            {"app.py": CLEAN},
            sources={"app.py": CLEAN.encode("utf-8"), "other.py": b"x = 1\n"},
        )


def test_a_file_with_nothing_to_write_may_be_left_out(tmp_path: Path) -> None:
    """`quiet.py` names the SDK in prose only, so its rows are `not_a_usage`."""
    quiet = '"""Mentions acme.sdk and imports nothing."""\n'
    run = acme.repository(
        tmp_path,
        {"app.py": CLEAN, "quiet.py": quiet},
        sources={"app.py": CLEAN.encode("utf-8")},
    )
    assert [outcome.path for outcome in run.files] == ["app.py"]
    assert [plan.path for plan in run.plans] == ["app.py", "quiet.py"]


def test_the_dual_import_policy_is_refused_because_no_rule_implements_it(
    tmp_path: Path,
) -> None:
    """No rule keeps both imports, so a refused group would call a module the rename removed."""
    with pytest.raises(codemod.CodemodError, match="no rule implements"):
        acme.repository(tmp_path, {"app.py": CLEAN}, policy=ImpactPolicy(import_policy="dual"))


def test_a_file_that_does_not_parse_is_never_handed_to_a_rule(tmp_path: Path) -> None:
    run = acme.repository(tmp_path, {"broken.py": "import acme.sdk\ndef (:\n"})
    assert run.files == ()
    assert [row.bail for row in run.plans[0].findings] == ["input_does_not_parse"]


def test_applying_twice_equals_applying_once(tmp_path: Path) -> None:
    """With the legacy pin gone F-2 has nothing to grade, so there is no manifest outcome at all."""
    first = acme.repository(tmp_path / "one", {"app.py": CLEAN, "requirements.txt": MANIFEST})
    written = {outcome.path: outcome.after.decode("utf-8") for outcome in first.outcomes}
    assert set(written) == {"app.py", "requirements.txt"}

    second = acme.repository(tmp_path / "two", written)
    assert [row for row in second.edits if row.status == "auto"] == []
    assert second.written == ()
    assert second.manifests == ()


def test_the_driver_writes_nothing(tmp_path: Path) -> None:
    """Writing is the caller's: a driver that wrote would leave it nothing to refuse."""
    files = {"app.py": CLEAN, "requirements.txt": MANIFEST}
    run = acme.repository(tmp_path, files)
    assert run.written, "a run that wrote nothing could not prove this"
    assert {
        path.relative_to(tmp_path).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file()
    } == files


def test_a_file_this_run_does_not_write_is_not_parsed_a_second_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`parse.gates` is the costliest per-file step, and unchanged bytes already passed it."""
    files = {"writes.py": CLEAN, "quiet.py": '"""Mentions acme.sdk in prose."""\n'}
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8", newline="\n")
    scan = runner.scan(tmp_path, Config(), acme.SPEC, jobs=1)
    sources = {name: text.encode("utf-8") for name, text in files.items()}

    asked: list[str] = []
    gates = parse.gates

    def spy(path: str, data: bytes) -> parse.Read:
        asked.append(path)
        return gates(path, data)

    monkeypatch.setattr(parse, "gates", spy)
    run = codemod.run(scan, sources, acme.PACK, acme.SPEC)
    assert [outcome.path for outcome in run.written] == ["writes.py"]
    assert asked == ["writes.py"]


def test_the_codes_this_module_raises_are_the_ones_it_declares(tmp_path: Path) -> None:
    assert {
        "usage_unmapped",
        "output_does_not_parse",
        "output_names_unresolved",
        "configure_consumed_elsewhere",
    } == codemod.BAILS
    assert codemod.UNCLAIMED in codemod.BAILS
    assert codemod.GATE in codemod.BAILS
    assert codemod.UNRESOLVED in codemod.BAILS
    assert codemod.CONSUMED in codemod.BAILS


def test_the_rows_of_one_file_are_in_line_order(tmp_path: Path) -> None:
    """The driver appends its row last; `PROBE` sits above two rule rows, so sorting is tested."""
    source = '''"""The unclaimed row is not the last one."""

import acme.sdk as sdk

PROBE = sdk.measure

sdk.configure(key="k")

M = sdk.Model("m")
'''
    run = acme.repository(tmp_path, {"app.py": source})
    lines = [row.line for row in run.files[0].edits]
    assert lines == sorted(lines)
    assert [row.reason for row in run.files[0].edits][1] == "usage_unmapped"


def test_a_file_whose_parse_loses_a_byte_is_not_written(tmp_path: Path) -> None:
    """libcst drops a bare-CR file's final byte, so the re-render differs with nothing eligible.

    Returning it would hand the writer a file it decided not to change, one byte shorter.
    """
    source = 'import acme.sdk as sdk\rsdk.configure(key="k")\r'
    run = acme.repository(tmp_path, {"app.py": source})
    outcome = run.files[0]
    assert outcome.before == source.encode("utf-8")
    assert outcome.after == outcome.before
    assert outcome.written is False
    assert run.written == ()
    assert {row.bail for row in run.plans[0].findings} == {"roundtrip_mismatch"}
