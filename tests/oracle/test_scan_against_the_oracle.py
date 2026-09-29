"""The scan and impact plan, asserted equal to the hand-written oracle keys.

Raised and graded codes must match both ways. One tolerance (`SCAN_VOCABULARY.md` §10): a plan's
`eligible` matches a fix-time key's `auto`, a different claim, not a weaker one.
"""

from __future__ import annotations

import harness
import pytest

from obelize.impact import dataflow, planner
from obelize.models import BAIL_CODES, REPO_ATOMICITY_BAIL, BailCode
from obelize.scan import analysis, manifests, parse, reach

# Every code the passes raise, as each module declares it; `input_does_not_parse` is the reader's.
IMPACT_OWNED: frozenset[BailCode] = (
    analysis.BAILS
    | dataflow.BAILS
    | manifests.BAILS
    | planner.BAILS
    | reach.BAILS
    | {parse.PARSE_BAIL}
)

# Graded but unranked by §6: a manifest row names one declaration, so `manifest_code_mismatch`
# never meets `repo_not_fully_migrated`; `model_object_read_elsewhere` lands only where none fired.
UNRANKED: frozenset[BailCode] = frozenset({"manifest_code_mismatch", reach.CODE})

# §6's full ladder. Repository atomicity is rung 6, deliberately last: it names no concrete defect.
RUNG: dict[BailCode, int] = {
    **planner.LADDER,
    REPO_ATOMICITY_BAIL: 6,
    manifests.TRANSITIVE_BAIL: 6,
}

# Kinds that keep the legacy distribution imported, from the key so `scan/manifests.py` must agree.
IMPORTING: frozenset[str] = frozenset({"dynamic", "import", "parse_error", "star_import"})

CASE_NAMES = sorted(harness.CASES)


@pytest.fixture(scope="module", params=CASE_NAMES)
def case(request: pytest.FixtureRequest) -> harness.Case:
    """Module-scoped: each load resolves libcst metadata."""
    return harness.load(str(request.param))


def test_every_graded_finding_is_produced(case: harness.Case) -> None:
    """Both directions: a missing row is an unseen usage, an extra row a claim nobody reviewed."""
    want = {harness.expected(row) for row in case.graded}
    got = set(case.by_key())
    assert want == got, (
        f"{case.name}: missing {sorted(want - got)}\nunexpected {sorted(got - want)}"
    )


def test_nothing_is_reported_on_a_must_not_report_line(case: harness.Case) -> None:
    """Keyed by file and line, plus symbol where a line carries both."""
    by_line: dict[tuple[str, int], set[str | None]] = {}
    for key in case.by_key():
        by_line.setdefault((key[0], key[1]), set()).add(key[4])

    for row in case.key.get("must_not_report") or []:
        at = (str(row["file"]), int(row["line"]))
        reported = by_line.get(at)
        if reported is None:
            continue
        named = row.get("symbol")
        assert named is not None, f"{case.name}: {at[0]}:{at[1]} is reported and must not be"
        assert harness.symbol(named) not in reported, (
            f"{case.name}: {at[0]}:{at[1]} reports {named!r}, which the key forbids"
        )


def test_the_graded_status_and_bail_match_the_key_exactly(case: harness.Case) -> None:
    """`caused_by` is the whole cause set, in order: emitting only the first cause fails."""
    produced = case.by_key()
    for row in case.graded:
        finding = produced[harness.expected(row)]
        where = f"{case.name}: {row['file']}:{row['line']} {row['symbol']}"
        graded: BailCode | None = row.get("bail")
        if graded is None:
            assert (finding.scan_status, finding.bail) == (
                harness.scan_status(row["verdict"]),
                None,
            ), f"{where} is graded {row['verdict']!r} with no bail"
            continue
        assert graded in IMPACT_OWNED, f"{where} grades {graded!r}, which no pass claims"
        assert (finding.scan_status, finding.bail) == (row["verdict"], graded), where
        causes = row.get("caused_by")
        assert finding.caused_by == (None if causes is None else tuple(causes)), (
            f"{where}: the plan says caused_by={finding.caused_by} and the key says {causes}"
        )


def test_every_declared_binding_is_found_and_withheld_at_the_graded_code(
    case: harness.Case,
) -> None:
    """Subset only: the key omits `chat_async_self`'s `chat`. `use_lines` (what a group is atomic
    over) and the bail (its own defect, else what withheld its lines) are exact."""
    for row in case.key.get("bindings") or []:
        want = (row["kind"], row["name"], row["scope"], row["ctor_line"])
        matches = [
            binding
            for binding in case.bindings
            if (binding.kind, binding.name, binding.scope, binding.ctor_line) == want
            and (row.get("file") is None or binding.path == row["file"])
        ]
        assert matches, (
            f"{case.name}: no binding matches {want}; found "
            f"{sorted((b.path, b.kind, b.name, b.scope, b.ctor_line) for b in case.bindings)}"
        )
        binding = matches[0]
        assert list(binding.use_lines) == list(row.get("use_lines") or []), (
            f"{case.name}: {want} uses {list(binding.use_lines)}, key says {row.get('use_lines')}"
        )
        assert (binding.scan_status, binding.bail) == (
            harness.scan_status(row["verdict"]),
            row.get("bail"),
        ), f"{case.name}: {want} is graded {row['verdict']!r}/{row.get('bail')!r}"


def test_a_binding_escapes_exactly_where_the_key_grades_it(case: harness.Case) -> None:
    """The biconditional pins both carve-outs: `if MODEL is None` is no escape, while
    `len(self.chat.history)`, an attribute read of the bound object, is one."""
    found = {
        (path, receiver.kind, receiver.name, receiver.scope, receiver.ctor_line): receiver
        for path, receiver in case.receivers
    }
    for row in case.key.get("bindings") or []:
        want = (row["kind"], row["name"], row["scope"], row["ctor_line"])
        receiver = next(
            receiver
            for key, receiver in found.items()
            if key[1:] == want and (row.get("file") is None or key[0] == row["file"])
        )
        escapes = row.get("bail") == "model_object_escapes"
        assert bool(receiver.escape_lines) is escapes, (
            f"{case.name}: {want} has escapes {list(receiver.escape_lines)} and the key "
            f"{'does' if escapes else 'does not'} grade it `model_object_escapes`"
        )


def test_two_scans_of_the_same_bytes_agree(case: harness.Case) -> None:
    """libcst returns identity-hashed sets; a re-resolved second pass exposes an unsorted
    iteration, so lists are compared. `test_scan_determinism.py` varies the seed and `--jobs`."""
    again = harness.load(case.name)
    assert [finding.model_dump_json() for finding in again.findings] == [
        finding.model_dump_json() for finding in case.findings
    ]


def test_what_the_passes_claim_is_exactly_what_the_oracle_grades() -> None:
    """A graded code nothing raises is an unwritten rule; one claimed but ungraded, unmeasured."""
    graded: set[str] = set()
    for name in CASE_NAMES:
        key = harness.load(name).key
        for section in ("findings", "bindings"):
            for row in key.get(section) or []:
                if row.get("bail"):
                    graded.add(row["bail"])
                graded.update(row.get("caused_by") or ())
    assert graded <= BAIL_CODES
    assert graded == set(IMPACT_OWNED), (
        f"graded and raised by nothing: {sorted(graded - set(IMPACT_OWNED))}; "
        f"claimed and never graded: {sorted(set(IMPACT_OWNED) - graded)}"
    )


def test_every_rung_is_known_for_every_code_the_ladder_ranks() -> None:
    assert set(analysis.RUNG) == set(analysis.BAILS)
    assert set(dataflow.RUNG) == set(dataflow.BAILS)
    assert set(planner.RUNG) == set(planner.BAILS)
    assert UNRANKED < manifests.BAILS | reach.BAILS
    assert set(IMPACT_OWNED) - UNRANKED <= set(RUNG)


def test_the_files_that_block_the_manifest_edit_are_the_ones_the_key_leaves_importing(
    case: harness.Case,
) -> None:
    """ADR-010 F-2 evidence, read off the key rather than the rule under test: a non-`auto` import
    (dynamic and unparsed too) or string mock target (`mock.patch` imports it); not prose."""
    expected = {
        str(row["file"])
        for row in case.graded
        if row["verdict"] != "auto"
        and (row["kind"] in IMPORTING or row["confidence_reason"] == "mock_patch_target")
    }
    assert set(case.manifests.blocking) == expected


# Excluded files that still match the prefilter (ADR-010 F-2), read off the prose of
# `examples/gemini-legacy-app/ground_truth.yaml` and `harness.yaml`, not the pass.
EXCLUDED_HITS: dict[str, tuple[str, ...]] = {
    "encoding": ("_build.py",),
    "gemini-legacy-app": ("scripts/oneoff_backfill.py",),
}


def test_the_excluded_files_the_report_names_are_the_ones_the_documents_name(
    case: harness.Case,
) -> None:
    """The empty cases matter: an over-broad "excluded" would name every `**/*.after.py` key."""
    assert case.manifests.excluded == EXCLUDED_HITS.get(case.name, ())


def test_the_harness_excludes_only_patterns_that_match_something() -> None:
    """A pattern for a renamed file excludes nothing; each owes a `why`, since excluding is how a
    case passes by scanning less."""
    document = harness.document()
    for name, section in document.items():
        patterns = list(section["exclude"])
        assert sorted(section["why"]) == sorted(patterns), (
            f"{name}: every excluded pattern needs a reason, and only those"
        )
        roots = list(harness.CASES.values()) if name == "all" else [harness.CASES[name]]
        for pattern in patterns:
            matched = [path for root in roots for path in root.rglob(pattern.removeprefix("**/"))]
            assert matched, f"{name}: nothing matches the excluded pattern {pattern!r}"


def test_every_case_with_an_answer_key_is_graded_here() -> None:
    """`tests/unit/test_fixture_vocabulary.py` checks a key's words; only this checks the scan."""
    keys = {
        path.parent.name
        for path in [
            *harness.ROOT.joinpath("tests", "fixtures", "scan").glob("*/ground_truth.yaml"),
            *harness.ROOT.joinpath("examples").glob("*/ground_truth.yaml"),
        ]
    }
    assert keys == set(CASE_NAMES)


def test_the_key_and_the_scan_agree_on_what_a_file_contains(case: harness.Case) -> None:
    """An over-broad harness exclusion would otherwise pass a case by scanning nothing."""
    graded_files = {str(row["file"]) for row in case.graded}
    reported = {finding.path for finding in case.findings}
    assert graded_files <= reported | {""}, (
        f"{case.name}: the key grades findings in {sorted(graded_files - reported)} "
        f"and the scan reported none there"
    )
