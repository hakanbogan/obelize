"""Fixture answer keys may use only the vocabulary `src/obelize/models.py` declares.

`tests/unit/test_models.py` ties the models to `docs/SCAN_VOCABULARY.md`, so the document has one
parser and no link in document -> code -> fixtures repeats a list.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from obelize.models import (
    ATOMICITY_BAIL,
    BAIL_CODES,
    BINDING_KINDS,
    CONFIDENCE_REASONS,
    FINDING_KINDS,
    IMPORT_BAILS,
    IMPORT_KINDS,
    VERDICTS,
    WARNING_CODES,
    WITHHELD,
    Edit,
)

ROOT = Path(__file__).resolve().parents[2]
COVERAGE = ROOT / "tests" / "fixtures" / "scan" / "COVERAGE.md"
GROUND_TRUTHS = sorted(
    [
        *(ROOT / "tests" / "fixtures" / "scan").glob("*/ground_truth.yaml"),
        ROOT / "examples" / "gemini-legacy-app" / "ground_truth.yaml",
    ]
)

AFTER_FILE_IS = {"fix_apply_output", "human_answer_key", "none"}
# The one bail naming no defect of its own, so it must name the ones that do.
ATOMICITY = ATOMICITY_BAIL
# ADR-010 F-6: mandatory on a module-level `configure` with a non-literal key.
EAGER_CLIENT = "client_constructed_eagerly"

KINDS = FINDING_KINDS
REASONS = CONFIDENCE_REASONS
BAILS = BAIL_CODES
WARNINGS = WARNING_CODES


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


CASES = [(p.parent.name, _load(p)) for p in GROUND_TRUTHS]
ROWS = [
    (name, kind, row)
    for name, data in CASES
    for kind in ("findings", "bindings")
    for row in (data.get(kind) or [])
]


def test_every_fixture_was_found() -> None:
    assert {name for name, _ in CASES} == {
        "basic",
        "chat_async_self",
        "encoding",
        "escapes",
        "import_forms",
        "manifests",
        "negative",
        "transitive",
        "gemini-legacy-app",
    }


@pytest.mark.parametrize(("name", "data"), CASES, ids=[n for n, _ in CASES])
def test_after_file_is_declared_and_consistent_with_the_verdicts(
    name: str, data: dict[str, Any]
) -> None:
    declared = data.get("after_file_is")
    assert declared in AFTER_FILE_IS, f"{name}: after_file_is={declared!r}"

    directory = next(p.parent for p in GROUND_TRUTHS if p.parent.name == name)
    has_answer_key = any(directory.rglob("*.after.py"))
    assert (declared != "none") == has_answer_key, (
        f"{name}: after_file_is={declared!r} but "
        f"{'an' if has_answer_key else 'no'} .after.py exists"
    )

    if declared != "fix_apply_output":
        return

    # Per file: a case may mix files that migrate with files never touched (`encoding/`).
    verdicts: dict[str, set[str]] = {}
    for finding in data["findings"]:
        if str(finding["file"]).endswith(".py"):
            verdicts.setdefault(finding["file"], set()).add(finding["verdict"])

    for relative, graded in sorted(verdicts.items()):
        key = directory / (relative[: -len(".py")] + ".after.py")
        if graded == {"auto"}:
            assert key.exists(), (
                f"{name}: every finding in {relative} is `auto`, so `obelize fix --apply` "
                f"rewrites the file -- and nothing says what it must produce. Add "
                f"{key.relative_to(directory)}, or the case grades its inputs and not its outputs."
            )
        else:
            assert not key.exists(), (
                f"{name}: {relative} has an answer key but is not all-`auto` ({sorted(graded)}). "
                f"Under `fix_apply_output` a key means `fix --apply` produces it byte for byte, "
                f"which a withheld finding contradicts."
            )


@pytest.mark.parametrize(
    ("name", "section", "row"),
    ROWS,
    ids=[
        f"{n}:{s}:{r.get('file', r.get('name'))}:{r.get('line', r.get('ctor_line'))}"
        for n, s, r in ROWS
    ],
)
def test_every_row_uses_only_attested_vocabulary(
    name: str, section: str, row: dict[str, Any]
) -> None:
    verdict = row["verdict"]
    assert verdict in VERDICTS, f"{name}: verdict {verdict!r}"

    if section == "findings":
        assert row["kind"] in KINDS, f"{name}: kind {row['kind']!r}"
        reason = row.get("confidence_reason")
        assert reason is None or reason in REASONS, f"{name}: reason {reason!r}"
    else:
        assert row["kind"] in BINDING_KINDS, f"{name}: binding kind {row['kind']!r}"

    bail = row.get("bail")
    if verdict in WITHHELD:
        assert bail in BAILS, (
            f"{name}: verdict {verdict!r} withholds the hunk, so it must name a bail "
            f"from docs/SCAN_VOCABULARY.md section 4; got {bail!r}"
        )
    else:
        assert bail is None, f"{name}: verdict {verdict!r} must not carry a bail, got {bail!r}"

    for warning in row.get("warnings") or []:
        assert warning in WARNINGS, f"{name}: warning {warning!r}"


@pytest.mark.parametrize(
    ("name", "section", "row"),
    ROWS,
    ids=[
        f"{n}:{s}:{r.get('file', r.get('name'))}:{r.get('line', r.get('ctor_line'))}"
        for n, s, r in ROWS
    ],
)
def test_an_import_finding_only_carries_a_bail_about_the_import(
    name: str, section: str, row: dict[str, Any]
) -> None:
    """Another group's bail on a resolved import misreports it and double-counts the defect."""
    if section != "findings" or row["kind"] not in IMPORT_KINDS:
        return
    bail = row.get("bail")
    if bail is None:
        return
    assert bail in IMPORT_BAILS, (
        f"{name}: {row['file']}:{row['line']} is an import finding carrying bail {bail!r}, "
        f"which docs/SCAN_VOCABULARY.md section 6 does not allow on an import. If the import "
        f"itself resolved, the code is `{ATOMICITY}` with `caused_by: [{bail}]`."
    )


@pytest.mark.parametrize(
    ("name", "section", "row"),
    ROWS,
    ids=[
        f"{n}:{s}:{r.get('file', r.get('name'))}:{r.get('line', r.get('ctor_line'))}"
        for n, s, r in ROWS
    ],
)
def test_caused_by_is_present_exactly_where_atomicity_withheld_the_finding(
    name: str, section: str, row: dict[str, Any]
) -> None:
    if section == "bindings":
        # Atomicity is per file; a binding row (often with no `file` key) names only its own defect.
        assert row.get("bail") != ATOMICITY, (
            f"{name}: a bindings row may not carry {ATOMICITY!r}; see SCAN_VOCABULARY.md section 6"
        )
        assert row.get("caused_by") is None, f"{name}: a bindings row may not carry `caused_by`"
        return

    caused_by = row.get("caused_by")
    if row.get("bail") != ATOMICITY:
        assert caused_by is None, (
            f"{name}: bail {row.get('bail')!r} names its own defect, so it must not carry "
            f"`caused_by`; got {caused_by!r}"
        )
        return

    assert isinstance(caused_by, list), (
        f"{name}: bail {ATOMICITY!r} must carry a `caused_by` list, got {caused_by!r}"
    )
    assert caused_by, f"{name}: bail {ATOMICITY!r} must carry at least one cause"
    assert caused_by == sorted(set(caused_by)), (
        f"{name}: `caused_by` must be sorted and de-duplicated, got {caused_by!r}"
    )
    unknown = [code for code in caused_by if code not in BAILS]
    assert not unknown, f"{name}: `caused_by` names codes outside section 4: {unknown}"
    assert ATOMICITY not in caused_by, f"{name}: `caused_by` must not name {ATOMICITY!r} itself"


@pytest.mark.parametrize(("name", "data"), CASES, ids=[n for n, _ in CASES])
def test_every_caused_by_code_is_witnessed_in_the_same_file(
    name: str, data: dict[str, Any]
) -> None:
    """Each `caused_by` code must be another row's bail in the same file."""
    bails_by_file: dict[str, set[str]] = {}
    for finding in data["findings"]:
        if finding.get("bail"):
            bails_by_file.setdefault(finding["file"], set()).add(finding["bail"])

    for finding in data["findings"]:
        if finding.get("bail") != ATOMICITY:
            continue
        witnesses = bails_by_file.get(finding["file"], set()) - {ATOMICITY}
        assert finding.get("caused_by") == sorted(witnesses), (
            f"{name}: {finding['file']}:{finding['line']} must name EVERY code that withheld "
            f"another finding in that file, sorted. Expected {sorted(witnesses)}, "
            f"got {finding.get('caused_by')}. `caused_by` is the whole cause set, not a sample: "
            f"an implementation that emits the first cause per file must fail here."
        )


# COVERAGE.md's census per case, written out so a moved verdict names its case.
CENSUS = {
    "basic": {"auto": 7, "needs_review": 0, "unsupported": 0, "not_a_usage": 0},
    "chat_async_self": {"auto": 9, "needs_review": 0, "unsupported": 0, "not_a_usage": 0},
    "encoding": {"auto": 16, "needs_review": 4, "unsupported": 2, "not_a_usage": 0},
    "escapes": {"auto": 0, "needs_review": 54, "unsupported": 0, "not_a_usage": 0},
    "import_forms": {"auto": 27, "needs_review": 0, "unsupported": 0, "not_a_usage": 0},
    "manifests": {"auto": 10, "needs_review": 10, "unsupported": 0, "not_a_usage": 1},
    "gemini-legacy-app": {"auto": 3, "needs_review": 11, "unsupported": 1, "not_a_usage": 2},
    "negative": {"auto": 0, "needs_review": 0, "unsupported": 0, "not_a_usage": 6},
    "transitive": {"auto": 5, "needs_review": 1, "unsupported": 0, "not_a_usage": 0},
}
TOTALS = {"findings": 169, "bindings": 25, "must_not_report": 107, "must_not_autofix": 1}


@pytest.mark.parametrize(("name", "data"), CASES, ids=[n for n, _ in CASES])
def test_the_oracle_census_is_what_coverage_md_publishes(name: str, data: dict[str, Any]) -> None:
    """The oracle measures the benchmark, so no verdict may move silently."""
    counted = dict.fromkeys(("auto", "needs_review", "unsupported", "not_a_usage"), 0)
    for finding in data["findings"]:
        counted[finding["verdict"]] += 1
    assert counted == CENSUS[name], (
        f"{name}: verdict census moved. Update tests/fixtures/scan/COVERAGE.md and say why in "
        f"the same commit -- this file is the measurement oracle."
    )


# COVERAGE.md's census sentence; the two numbers it spells in words go through `WORDS`.
CENSUS_SENTENCE = re.compile(
    r"(\w+) cases, (\d+) graded findings \((\d+) `auto`, (\d+) `needs_review`, "
    r"(\d+) `unsupported`, (\d+) `not_a_usage`\), (\d+) bindings, (\d+) "
    r"`must_not_report` rows and (\w+) `must_not_autofix` row"
)
WORDS = {"one": 1, "two": 2, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def published_census(text: str) -> dict[str, int]:
    """COVERAGE.md's numbers, keyed like `CENSUS` and `TOTALS`."""
    match = CENSUS_SENTENCE.search(" ".join(text.split()))
    assert match, "COVERAGE.md no longer carries its census sentence"
    cases, findings, auto, review, unsupported, usage, bindings, mnr, mna = match.groups()
    return {
        "cases": WORDS[cases.lower()],
        "findings": int(findings),
        "auto": int(auto),
        "needs_review": int(review),
        "unsupported": int(unsupported),
        "not_a_usage": int(usage),
        "bindings": int(bindings),
        "must_not_report": int(mnr),
        "must_not_autofix": WORDS[mna.lower()],
    }


def test_the_census_coverage_md_prints_is_the_one_this_file_counts() -> None:
    published = published_census(COVERAGE.read_text(encoding="utf-8"))
    counted = {
        verdict: sum(split[verdict] for split in CENSUS.values())
        for verdict in ("auto", "needs_review", "unsupported", "not_a_usage")
    }
    assert published == {"cases": len(CENSUS), **TOTALS, **counted}


def test_a_census_sentence_that_drifted_is_read_as_the_wrong_number() -> None:
    text = (
        "Eight cases, 150 graded findings (68 `auto`, 71 `needs_review`, 3 `unsupported`, "
        "9 `not_a_usage`), 21 bindings, 102\n`must_not_report` rows and one `must_not_autofix` row."
    )
    assert published_census(text)["findings"] == 150


def test_the_oracle_totals_are_what_coverage_md_publishes() -> None:
    totals = {
        "findings": sum(len(d["findings"]) for _, d in CASES),
        "bindings": sum(len(d.get("bindings") or []) for _, d in CASES),
        "must_not_report": sum(len(d.get("must_not_report") or []) for _, d in CASES),
        "must_not_autofix": sum(len(d.get("must_not_autofix") or []) for _, d in CASES),
    }
    assert totals == TOTALS, totals


@pytest.mark.parametrize(("name", "data"), CASES, ids=[n for n, _ in CASES])
def test_a_line_is_never_both_a_finding_and_a_must_not_report(
    name: str, data: dict[str, Any]
) -> None:
    """Unless the must_not_report row names a different symbol on that line."""
    by_line: dict[tuple[str, int], set[str]] = {}
    for f in data["findings"]:
        by_line.setdefault((f["file"], f["line"]), set()).add(str(f["symbol"]))

    for row in data.get("must_not_report") or []:
        key = (row["file"], row["line"])
        if key not in by_line:
            continue
        symbol = row.get("symbol")
        assert symbol is not None, (
            f"{name}: {key[0]}:{key[1]} is both a finding and a must_not_report. "
            f"Give the must_not_report row a `symbol` naming what must NOT be reported, "
            f"or move it to `must_not_autofix`."
        )
        assert symbol not in by_line[key], (
            f"{name}: {key[0]}:{key[1]} reports and must-not-reports the same symbol {symbol!r}"
        )


@pytest.mark.parametrize(("name", "data"), CASES, ids=[n for n, _ in CASES])
def test_referenced_fixture_files_exist(name: str, data: dict[str, Any]) -> None:
    directory = next(p.parent for p in GROUND_TRUTHS if p.parent.name == name)
    referenced = {
        row["file"]
        for key in ("findings", "must_not_report", "must_not_autofix")
        for row in (data.get(key) or [])
        if "file" in row
    }
    missing = sorted(rel for rel in referenced if not (directory / rel).exists())
    assert not missing, f"{name}: ground truth names files that do not exist: {missing}"


@pytest.mark.parametrize(("name", "data"), CASES, ids=[n for n, _ in CASES])
def test_every_referenced_line_exists_in_its_file(name: str, data: dict[str, Any]) -> None:
    """`bytes.splitlines()` counts CR, LF and CRLF as libcst does (see `encoding/bare_cr.py`)."""
    directory = next(p.parent for p in GROUND_TRUTHS if p.parent.name == name)
    for key in ("findings", "must_not_report", "must_not_autofix"):
        for row in data.get(key) or []:
            if "file" not in row or "line" not in row:
                continue
            total = len((directory / row["file"]).read_bytes().splitlines())
            assert 1 <= row["line"] <= total, (
                f"{name}: {key} points at {row['file']}:{row['line']}, "
                f"but that file has {total} lines"
            )


@pytest.mark.parametrize(("name", "data"), CASES, ids=[n for n, _ in CASES])
def test_a_module_level_configure_carries_the_eager_client_warning(
    name: str, data: dict[str, Any]
) -> None:
    """Module level is read from the line's first byte (encoding-free), so no key can opt out."""
    directory = next(p.parent for p in GROUND_TRUTHS if p.parent.name == name)
    for finding in data["findings"]:
        if finding["verdict"] != "auto" or not str(finding["symbol"]).endswith(".configure"):
            continue
        source = (directory / finding["file"]).read_bytes()
        line = source.splitlines()[finding["line"] - 1]
        at_import_time = not line[:1].isspace()
        carries = EAGER_CLIENT in (finding.get("warnings") or [])
        assert carries is at_import_time, (
            f"{name}: {finding['file']}:{finding['line']} is "
            f"{'at module level' if at_import_time else 'inside a function or method'} and "
            f"{'does not carry' if at_import_time else 'carries'} {EAGER_CLIENT!r}. "
            f"ADR-010 F-6: a `configure` that becomes a module-level `genai.Client(...)` turns a "
            f"missing key from a first-call failure into an import-time `ValueError`, and the "
            f"warning is the only thing that says so."
        )


@pytest.mark.parametrize(
    ("name", "section", "row"),
    ROWS,
    ids=[
        f"{n}:{s}:{r.get('file', r.get('name'))}:{r.get('line', r.get('ctor_line'))}"
        for n, s, r in ROWS
    ],
)
def test_every_graded_row_is_representable_as_an_edit(
    name: str, section: str, row: dict[str, Any]
) -> None:
    """Answer keys and the runtime `Edit` must share one shape; only `rule_id` is supplied here."""
    verdict = row["verdict"]
    if verdict == "not_a_usage":
        return
    caused_by = row.get("caused_by")
    try:
        edit = Edit(
            path=row.get("file") or "fixture.py",
            line=row.get("line") or row["ctor_line"],
            status=verdict,
            rule_id="oracle" if verdict == "auto" else None,
            reason=row.get("bail"),
            caused_by=tuple(caused_by) if caused_by is not None else None,
            warnings=tuple(row.get("warnings") or ()),
        )
    except ValidationError as error:
        pytest.fail(f"{name}: {row} is not a legal Edit:\n{error}")
    assert edit.status == verdict
