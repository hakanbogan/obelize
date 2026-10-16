"""The terminal summary and `REPORT.md`: the claims a reader relies on, not their wording.

Empty sections are asserted too, since silence looks like a scan that never ran; trees are real
so the renderer never agrees with a value no pass produces.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import cast

import pytest

from obelize import gitutil
from obelize.config import load as load_config
from obelize.evidence import report, run_dir
from obelize.models import (
    BAIL_ACTIONS,
    WARNING_MEANINGS,
    CommandRecord,
    Edit,
    Finding,
    ManifestPlan,
    PackRef,
    PlanDocument,
    ProposalRecord,
    RunModel,
    RunRecord,
    UndoFile,
    UndoRecord,
    VerifyRecord,
    Withheld,
)
from obelize.packs import loader
from obelize.scan import runner, runtime
from obelize.transforms.kinds.flag_only import Guide
from platforms import posix_only

BUNDLED = "gemini/google-generativeai-to-google-genai"

LEGACY = """import google.generativeai as genai

genai.configure(api_key="k")
MODEL = genai.GenerativeModel("gemini-1.5-flash")
"""

# The model escapes into a list: the group bails and the legacy import stays (F-2 withholds).
ESCAPES = LEGACY + "KEEP = [MODEL]\n"

PLAIN = "def add(left: int, right: int) -> int:\n    return left + right\n"

MANIFEST = "google-generativeai==0.8.6\n"


def _scan(root: Path) -> runner.Scan:
    pack = loader.load(BUNDLED)
    return runner.scan(root, load_config(root).config, loader.to_scan_spec(pack), jobs=1)


def _record(root: Path, scan: runner.Scan) -> RunRecord:
    loaded = load_config(root)
    return run_dir.compose(
        run_id=run_dir.new_id(run_dir.now(), "3f9a1c72"),
        scan=scan,
        packs=[run_dir.Used(loader.load(BUNDLED), scan.blocked[0] if scan.blocked else None)],
        config=loaded.config,
        source=loaded.source,
        git=gitutil.state(root),
        argv=("scan",),
        started=run_dir.now(),
        finished=run_dir.now(),
        total_ms=1,
        scan_ms=1,
    )


def _tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def quiet(tmp_path: Path) -> Path:
    return _tree(tmp_path / "quiet", {"plain.py": PLAIN})


@pytest.fixture
def loud(tmp_path: Path) -> Path:
    """Every section at once: findings, a bail, both of F-2's manifest lists, a parse error."""
    return _tree(
        tmp_path / "loud",
        {
            ".obelize.yml": 'exclude:\n  - "scripts/**"\n',
            "app.py": ESCAPES,
            "broken.py": "import google.generativeai\n\ndef broken(:\n    pass\n",
            "scripts/oneoff.py": LEGACY,
            "requirements.txt": MANIFEST,
        },
    )


@pytest.fixture
def pinned(tmp_path: Path) -> Path:
    """A legacy pin nothing imports: a manifest row with neither of F-2's lists behind it."""
    return _tree(tmp_path / "pinned", {"plain.py": PLAIN, "requirements.txt": MANIFEST})


def test_the_summary_names_the_pack_the_counts_and_where_the_evidence_went(loud: Path) -> None:
    scan = _scan(loud)
    lines = report.terminal(scan, "acme/pack 1.2.3", ".obelize/runs/x")
    assert lines[0] == "obelize scan  acme/pack 1.2.3"
    assert any(line.startswith("Evidence: .obelize/runs/x") for line in lines)
    headline = next(line for line in lines if "finding(s)" in line)
    assert headline.startswith(f"{scan.counts.files_selected} file(s) selected")
    assert "needs review" in headline


def test_every_finding_is_printed_under_the_file_it_is_in(loud: Path) -> None:
    scan = _scan(loud)
    text = "\n".join(report.terminal(scan, "p", None))
    for finding in scan.findings:
        assert f"  {finding.path}" in text
        assert str(finding.line) in text
    assert "Evidence:" not in text, "a run that wrote none must not claim one"


def test_a_scan_that_found_nothing_still_says_so(quiet: Path) -> None:
    """The prefilter selects `plain.py` but never parses it, which is why the counts differ."""
    lines = report.terminal(_scan(quiet), "p", None)
    assert lines[-1] == "1 file(s) selected, 0 parsed, 0 finding(s)"
    assert not [line for line in lines if line.startswith("Columns:")], "no table to explain"


def test_the_table_is_followed_by_what_its_columns_mean(loud: Path) -> None:
    scan = _scan(loud)
    lines = report.terminal(scan, "p", None)
    legend = (
        "Columns: line, kind, symbol, status, reason (blank when eligible). eligible: obelize "
        "fix will try to migrate it; needs_review: left for you, for the reason shown; "
        "unsupported: the new SDK has no equivalent; not_a_usage: shown for context only. fix "
        "leaves a file as it was when any row in it is needs_review or unsupported (for "
        "openai, any row in the repository)."
    )
    headline = next(index for index, line in enumerate(lines) if "finding(s)" in line)
    assert lines[headline - 3 : headline] == ["", legend, ""]
    last = max(index for index, line in enumerate(lines) if line.startswith("    "))
    assert last == headline - 4


def test_a_refusal_is_counted_in_the_summary_and_detailed_in_the_report(loud: Path) -> None:
    scan = _scan(loud)
    lines = report.terminal(scan, "p", None)
    assert any("were skipped or only partly read" in line for line in lines)
    assert any("dependency declaration(s)" in line for line in lines)


def test_the_blocked_repository_says_so_before_anything_else(tmp_path: Path) -> None:
    root = _tree(
        tmp_path / "old",
        {"pyproject.toml": '[project]\nname = "x"\nrequires-python = ">=3.9"\n', "app.py": LEGACY},
    )
    scan = _scan(root)
    lines = report.terminal(scan, "p", None)
    assert lines[2].startswith("pyproject.toml declares Python >=3.9, which allows")
    assert "plans no change" in lines[2]
    document = report.document(_record(root, scan), scan)
    assert "## Blocked\n\n`pyproject.toml` declares Python `>=3.9`, which allows" in document


APPLY = (
    " To apply it in a git repository, commit that change first: fix --apply refuses uncommitted "
    "changes unless you pass --allow-dirty."
)


@pytest.mark.parametrize(
    ("blocked", "says"),
    [
        (
            runtime.Blocked("runtime_unsupported", "new-sdk", "pyproject.toml", ">=3.8", ">=3.10"),
            "pyproject.toml declares Python >=3.8, which allows versions new-sdk does not install "
            "on, so this migration reports its findings and plans no change. To migrate, raise the "
            "minimum in pyproject.toml to >=3.10 and run again." + APPLY,
        ),
        (
            runtime.Blocked(
                "legacy_version_unsupported", "old-sdk", "requirements.txt", ">=1", ">=3"
            ),
            "requirements.txt declares old-sdk >=1, which allows versions this migration does "
            "not cover, so this migration reports its findings and plans no change. To migrate, "
            "pin old-sdk to >=3 in requirements.txt and run again." + APPLY,
        ),
        (
            runtime.Blocked("legacy_version_unsupported", "old-sdk", "requirements.txt", "", ">=3"),
            "requirements.txt declares old-sdk with no version, which allows versions this "
            "migration does not cover, so this migration reports its findings and plans no "
            "change. To migrate, pin old-sdk to >=3 in requirements.txt and run again." + APPLY,
        ),
        (
            runtime.Blocked("legacy_version_unsupported", "old-sdk", "pyproject.toml", None, ">=3"),
            "pyproject.toml declares old-sdk in a form obelize cannot read, so this migration "
            "reports its findings and plans no change. To migrate, write it as a plain "
            "requirement such as old-sdk>=3 in pyproject.toml and run again." + APPLY,
        ),
        (
            runtime.Blocked("legacy_version_unsupported", "old-sdk", "", None, ">=3"),
            "No manifest declares old-sdk, so the version in use is not known and this "
            "migration reports its findings and plans no change. To migrate, declare old-sdk>=3 "
            "in a manifest obelize reads, such as requirements.txt, and run again." + APPLY,
        ),
        (
            runtime.Blocked(
                "legacy_version_unsupported",
                "old-sdk",
                "requirements.txt",
                "",
                ">=3",
                "poetry.lock",
            ),
            "requirements.txt declares old-sdk with no version, which this migration would take "
            "as the newest release of old-sdk, but poetry.lock suggests another release is in use, "
            "so it reports its findings and plans no change. To migrate, pin old-sdk to >=3 in "
            "requirements.txt and run again." + APPLY,
        ),
        (
            runtime.Blocked(
                "legacy_version_unsupported", "old-sdk", "setup.py", ">=1", ">=3", "app/main.py"
            ),
            "setup.py declares old-sdk >=1, which this migration would take as the newest "
            "release of old-sdk, but app/main.py suggests another release is in use, so it "
            "reports its findings and plans no change. To migrate, pin old-sdk to >=3 in "
            "setup.py and run again." + APPLY,
        ),
    ],
    ids=[
        "python",
        "pinned-below",
        "unpinned",
        "unreadable",
        "undeclared",
        "newest-refuted-by-a-lock",
        "newest-refuted-by-code",
    ],
)
def test_a_blocked_run_names_the_declaration_and_what_would_unblock_it(
    blocked: runtime.Blocked, says: str
) -> None:
    assert report._blocked(blocked, report._bare) == says


def test_the_path_that_refuted_the_newest_release_is_a_code_span_in_the_report() -> None:
    blocked = runtime.Blocked(
        "legacy_version_unsupported", "old-sdk", "requirements.txt", "", ">=3", "poetry.lock"
    )
    assert "but `poetry.lock` suggests another release is in use" in report._blocked(
        blocked, report._code
    )


TOOK = (
    "old-sdk is declared with no version that rules out 3.0.1, so this migration takes it as "
    "3.0.1, its newest release. A repository that installs an older one needs that pinned in a "
    "manifest obelize reads."
)


def test_a_release_taken_for_a_version_nobody_wrote_down_is_said_once_for_each_package() -> None:
    assert report._assumed((("old-sdk", "3.0.1"),), report._bare) == [TOOK, ""]
    assert report._assumed((), report._bare) == []
    twice = report._assumed((("old-sdk", "3.0.1"), ("other", "1.2")), report._bare)
    assert [line for line in twice if line] == [
        TOOK,
        TOOK.replace("old-sdk", "other").replace("3.0.1", "1.2"),
    ]
    assert report._assumed((("old-sdk", "3.0.1"),), report._code)[0].startswith(
        "`old-sdk` is declared with no version that rules out `3.0.1`, so this migration takes it "
        "as `3.0.1`, its newest release."
    )


def test_the_summary_and_the_report_say_what_was_taken_before_the_rows(quiet: Path) -> None:
    scan = replace(_scan(quiet), assumed=(("old-sdk", "3.0.1"),))
    lines = report.terminal(scan, "p", None)
    assert lines[2:4] == [TOOK, ""]
    document = report.document(_record(quiet, scan), scan)
    assert "## Assumed\n\n`old-sdk` is declared with no version that rules out `3.0.1`" in document
    assert document.index("## Assumed") < document.index("## Findings")


def test_nothing_is_said_of_a_release_when_none_was_taken(quiet: Path) -> None:
    scan = _scan(quiet)
    assert not [line for line in report.terminal(scan, "p", None) if "its newest release" in line]
    assert "## Assumed" not in report.document(_record(quiet, scan), scan)


def test_the_report_puts_the_command_and_the_flag_of_a_blocked_run_in_code_spans() -> None:
    blocked = runtime.Blocked("legacy_version_unsupported", "old-sdk", "", None, ">=3")
    assert report._blocked(blocked, report._code).endswith(
        "declare `old-sdk>=3` in a manifest obelize reads, such as `requirements.txt`, and run "
        "again. To apply it in a git repository, commit that change first: `fix --apply` refuses "
        "uncommitted changes unless you pass `--allow-dirty`."
    )


def test_the_report_carries_the_run_id_the_pack_and_the_selection(loud: Path) -> None:
    scan = _scan(loud)
    record = _record(loud, scan)
    text = report.document(record, scan)
    assert text.startswith("# obelize scan\n")
    assert record.run_id in text
    assert record.packs[0].sha256 in text
    assert f"{scan.counts.files_parsed} parsed" in text
    assert text.endswith("\n")


def test_every_section_that_can_be_full_is_full(loud: Path) -> None:
    scan = _scan(loud)
    record = _record(loud, scan)
    text = report.document(record, scan)
    for heading in ("## Findings", "## Withheld", "## Dependency manifests", "## Limitations"):
        assert heading in text
    assert "Still importing the legacy distribution:" in text
    assert "Excluded from the scan but still importing it:" in text
    assert "`scripts/oneoff.py`" in text
    assert "`input_does_not_parse`" in text


def test_every_section_that_can_be_empty_says_which_emptiness_it_is(quiet: Path) -> None:
    scan = _scan(quiet)
    text = report.document(_record(quiet, scan), scan)
    assert "Nothing in this repository matched the pack." in text
    assert "No manifest declares the legacy distribution." in text
    assert "Every selected path was read." in text
    assert "## Withheld" not in text, "nothing was withheld, so there is no list of it"


def test_the_symbol_column_is_filled_for_every_kind_that_has_one(loud: Path) -> None:
    """A `parse_error` names no symbol, and an empty cell would read as a missing value."""
    scan = _scan(loud)
    text = report.document(_record(loud, scan), scan)
    refused = next(row for row in scan.findings if row.kind == "parse_error")
    assert refused.symbol is None
    assert f"| {refused.line} | parse_error | -- | unsupported | input_does_not_parse |" in text


def test_the_withheld_table_names_the_bail_and_what_caused_it(loud: Path) -> None:
    scan = _scan(loud)
    record = _record(loud, scan)
    text = report.document(record, scan)
    atomicity = [row for row in record.withheld if row.caused_by]
    assert atomicity, "the tree was built so that F-1 fires"
    for row in atomicity:
        assert ", ".join(row.caused_by or ()) in text


def test_the_withheld_rows_are_exactly_the_findings_a_rule_withheld(loud: Path) -> None:
    scan = _scan(loud)
    assert [finding.scan_status for finding in report.withheld_rows(scan.findings)] == [
        finding.scan_status
        for finding in scan.findings
        if finding.scan_status in {"needs_review", "unsupported"}
    ]


def test_a_manifest_row_with_nothing_behind_it_prints_neither_list(pinned: Path) -> None:
    scan = _scan(pinned)
    text = report.document(_record(pinned, scan), scan)
    assert (
        "- `requirements.txt`:1 `google-generativeai`: needs_review (`manifest_code_mismatch`)"
        in text
    )
    assert "Still importing" not in text
    assert "Excluded from the scan" not in text


def test_a_manifest_row_that_is_withheld_names_its_bail(loud: Path) -> None:
    scan = _scan(loud)
    text = report.document(_record(loud, scan), scan)
    withheld = [row for row in scan.manifests.findings if row.bail]
    assert withheld, "F-2 withholds the legacy pin while a file still imports it"
    for row in withheld:
        assert f"(`{row.bail}`)" in text


def test_a_record_and_a_driver_run_that_disagree_about_the_mode_are_refused(
    loud: Path,
) -> None:
    """`record.mode` picks the body; a mismatch is a caller bug a report would state as fact."""
    scan = _scan(loud)
    record = _record(loud, scan)
    plan = PlanDocument(
        obelize_version=record.obelize_version,
        packs=(
            PackRef(id=record.packs[0].id, version=record.packs[0].pack_version, sha256="0" * 64),
        ),
    )
    with pytest.raises(ValueError, match="'scan' record was rendered"):
        report.document(record, scan, None, plan)
    fixing = RunRecord.model_validate(
        {
            **record.model_dump(),
            "mode": "plan",
            "counts": {**record.counts.model_dump(), "eligible": 0, "auto": record.counts.eligible},
            "verify": {"status": "not_run", "reason": "dry_run"},
            "timings": {**record.timings.model_dump(), "plan_ms": 1},
        }
    )
    with pytest.raises(ValueError, match="'plan' record was rendered"):
        report.document(fixing, scan)


def test_the_two_status_splits_differ_in_exactly_their_first_member() -> None:
    """`eligible` is a scan's word and `auto` a fix's; the shared names mean the same in both."""
    assert report.SPLIT[0] == ("eligible", "eligible")
    assert report.FIX_SPLIT[0] == ("auto", "auto")
    assert report.SPLIT[1:] == report.FIX_SPLIT[1:]


def test_a_diff_line_carries_no_character_a_terminal_would_act_on() -> None:
    """The lines are the repository's bytes; a tab stays, and a CRLF ending loses just its CR."""
    patch = (
        b"+\tclear = '\x1b[2J'\r\n+flipped = '\xe2\x80\xae'\n+latin = '\xe9'\n+back = 'a\rb'\n"
        b"+stray = 1\r\r\n"
    )
    assert report.diff(patch, str(Path(".obelize/runs/r")), {}) == [
        "+\tclear = '\\x1b[2J'",
        "+flipped = '\\u202e'",
        "+latin = '\\xe9'",
        "+back = 'a\\rb'",
        "+stray = 1\\r",
        f"Diff: {Path('.obelize/runs/r/patch.diff')}",
    ]


def test_a_diff_is_cut_only_past_two_hundred_lines() -> None:
    whole = b"".join(b"+%d\n" % number for number in range(200))
    diff = Path("f", "patch.diff")
    assert report.diff(whole, "f", {})[-2:] == ["+199", f"Diff: {diff}"]
    cut = report.diff(whole + b"+200\n", "f", {})
    assert cut[-2:] == ["+199", f"Diff: {diff} (200 of 201 lines shown)"]


def test_a_file_in_the_run_folder_is_named_with_the_system_s_separator_throughout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows' path class, stubbed here: the folder comes spelled with backslashes, and a `/`
    joining a name to it would print both separators."""
    monkeypatch.setattr(report, "PurePath", PureWindowsPath)
    folder = "my repo\\.obelize\\runs\\r"
    assert report.diff(b"+x\n", folder, {})[-1] == f"Diff: {folder}\\patch.diff"
    missing = UndoFile(
        path="app.py",
        outcome="skipped",
        reason="missing",
        recorded_sha256="a" * 64,
        snapshot="snapshots/before/" + "b" * 64,
    )
    undone = UndoRecord(
        run_id="20260918T091407Z-3f9a1c72",
        obelize_version="0.1.0",
        exit_code=4,
        undone_at="2026-09-18T09:14:07Z",
        files=(missing,),
    )
    shown = report.reverted(undone, folder, f"{folder}\\undo.json")
    assert f"      original  {folder}\\snapshots\\before\\{'b' * 64}" in shown


def test_the_superseding_note_finds_the_baseline_by_its_heading_and_not_the_word(
    quiet: Path,
) -> None:
    """A file named for it is no baseline."""
    record = _record(quiet, _scan(quiet)).model_copy(
        update={"verify": VerifyRecord(status="not_run", reason="no_verify_commands")}
    )
    unverified = "# obelize fix\n\n| `Baseline.py` | 1 |\n\n### After the patch\n"
    verified = unverified + "\n### Baseline\n\n`pass`\n"
    assert report.superseded(unverified, record, "now").endswith(
        "No tests ran before the change.\n"
    )
    assert report.superseded(verified, record, "now").endswith(
        "The Baseline section above still shows the tests run before the change.\n"
    )


GUIDES = (Guide("acme/pack:flag-x", 2, "It has no counterpart.", "Port it by hand."),)


def test_the_terminal_says_what_the_pack_says_about_each_flagged_change(loud: Path) -> None:
    lines = report.terminal(_scan(loud), "p", None, GUIDES)
    at = lines.index("acme/pack:flag-x: 2 finding(s) flagged.")
    assert lines[at + 1 : at + 4] == [
        "  It has no counterpart.",
        "  Suggestion: Port it by hand.",
        "",
    ]
    assert lines.index(next(line for line in lines if "finding(s)" in line)) < at


def test_nothing_flagged_prints_no_guidance_anywhere(loud: Path) -> None:
    scan = _scan(loud)
    assert not [line for line in report.terminal(scan, "p", None) if "finding(s) flagged." in line]
    assert "## Guidance" not in report.document(_record(loud, scan), scan)


def test_the_report_carries_the_guidance_after_what_was_withheld(loud: Path) -> None:
    scan = _scan(loud)
    text = report.document(_record(loud, scan), scan, guides=GUIDES)
    block = (
        "## Guidance\n\nWhat each pack says about the findings it flagged.\n\n"
        "### `acme/pack:flag-x`\n\n2 finding(s). It has no counterpart.\n\n"
        "**Suggestion:** Port it by hand.\n\n"
    )
    assert block in text
    assert text.index("## Withheld") < text.index("## Guidance") < text.index("## Dependency")


def test_the_report_lists_what_each_pack_says_it_does_not_handle(loud: Path) -> None:
    """After the run's own limitations, so the table that names a skipped file stays first."""
    scan = _scan(loud)
    pack = loader.load(BUNDLED).pack
    text = report.document(_record(loud, scan), scan, packs=[pack])
    assert scan.limitations, "the tree was built so that one file cannot be parsed"
    heading = f"What `{pack.id}` says it does not handle (its guide: {pack.source.url}):"
    assert text.index("| Path | Code | Detail |") < text.index(heading)
    assert all(f"\n- {entry}\n" in text for entry in pack.limitations)


def test_a_clean_scan_still_names_what_the_pack_does_not_handle(quiet: Path) -> None:
    scan = _scan(quiet)
    pack = loader.load(BUNDLED).pack
    text = report.document(_record(quiet, scan), scan, packs=[pack])
    assert "Every selected path was read.\n\nWhat `" in text


def test_pack_text_reaches_the_report_as_text_and_not_as_markup(quiet: Path) -> None:
    scan = _scan(quiet)
    pack = loader.load(BUNDLED).pack.model_copy(update={"limitations": ("<img src=x> | *a*",)})
    hostile = Guide(
        "acme/pack:flag-x",
        1,
        "<script>a()</script> ![i](http://e/x.png) `c`",
        "[y](javascript:alert(1)) & \\",
    )
    text = report.document(_record(quiet, scan), scan, guides=(hostile,), packs=[pack])
    assert "1 finding(s). \\<script\\>a()\\</script\\> \\!\\[i\\](http://e/x.png) \\`c\\`\n" in text
    assert "**Suggestion:** \\[y\\](javascript:alert(1)) \\& \\\\\n" in text
    assert "- \\<img src=x\\> \\| \\*a\\*\n" in text


def test_the_packs_verification_suggestions_are_listed_and_not_run(quiet: Path) -> None:
    suggested = loader.load(BUNDLED).pack.verification
    assert suggested is not None
    verify = VerifyRecord(status="not_run", reason="no_verify_commands")
    lines = report._verification_section(verify, [loader.load(BUNDLED).pack])
    assert lines[-len(suggested.suggestions) - 3 :][:2] == ["Suggested by the packs, not run:", ""]
    assert [f"- {report._prose(text)}" for text in suggested.suggestions] == lines[
        -len(suggested.suggestions) - 1 : -1
    ]
    assert "Suggested" not in "\n".join(report._verification_section(verify, []))


def test_two_packs_that_suggest_the_same_tests_say_them_once(quiet: Path) -> None:
    pack = loader.load(BUNDLED).pack
    verify = VerifyRecord(status="not_run", reason="no_verify_commands")
    once = report._verification_section(verify, [pack])
    assert report._verification_section(verify, [pack, pack]) == once


def test_a_dry_run_shows_no_phase_it_did_not_attempt(quiet: Path) -> None:
    verify = VerifyRecord(status="not_run", reason="dry_run")
    lines = report._verification_section(verify, [])
    assert lines == ["## Verification", "", "**not_run** (`dry_run`)", ""]


def test_an_eligible_row_gives_no_confidence_code_and_a_withheld_one_its_reason(
    tmp_path: Path, loud: Path
) -> None:
    ready = _tree(tmp_path / "ready", {"app.py": LEGACY})
    rows = [line for line in report.terminal(_scan(ready), "p", None) if line.startswith("    ")]
    assert rows
    assert [line for line in rows if not line.endswith("eligible")] == []
    withheld = [line for line in report.terminal(_scan(loud), "p", None) if "needs_review" in line]
    assert any(line.endswith("model_object_escapes") for line in withheld)


@posix_only("Windows cannot create a name with a pipe or a backtick")
def test_a_name_that_would_break_the_report_is_skipped_and_cannot_end_a_cell(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path / "odd", {"ok.py": LEGACY, "p|q.py": LEGACY, "a`b.py": LEGACY})
    scan = _scan(root)
    text = report.document(_record(root, scan), scan)
    rows = [line for line in text.splitlines() if "`unusable_name`" in line]
    assert len(rows) == 2
    for row in rows:
        assert len(re.split(r"(?<!\\)\|", row)) == 5, row
    assert "p\\|q.py: " in text
    assert "a\\`b.py: " in text


def test_the_superseding_note_names_the_commands_that_ran_on_one_line(quiet: Path) -> None:
    """A repeat finds the note as a heading and one paragraph, so a newline would orphan it."""
    command = "sh -c 'echo `date`\nexit 0'"
    verify = VerifyRecord(
        status="pass",
        commands=(
            CommandRecord(command=command, source="cli", status="pass", exit_code=0, duration_ms=1),
        ),
    )
    record = _record(quiet, _scan(quiet)).model_copy(update={"verify": verify})
    once = report.superseded("# obelize fix\n", record, "now")
    note = once.rsplit("\n## Verified again\n", 1)[1].strip().splitlines()
    assert len(note) == 1, note
    assert "with ``sh -c 'echo `date`" + chr(92) + "nexit 0'``" in note[0]
    twice = report.superseded(once, record, "later")
    assert twice.count("checked this run again") == 1


def test_a_code_span_outlasts_the_backticks_inside_it() -> None:
    assert report._code("ls") == "`ls`"
    assert report._code("echo `date`") == "`` echo `date` ``"
    assert report._code("a`b") == "``a`b``"
    assert report._code("`a`") == "`` `a` ``"


def test_a_forged_note_above_the_real_one_cuts_nothing(quiet: Path) -> None:
    """A file name may hold line breaks: only the last note, a paragraph to the end, is replaced."""
    record = _record(quiet, _scan(quiet)).model_copy(
        update={"verify": VerifyRecord(status="not_run", reason="no_verify_commands")}
    )
    forged = f"x\n{report.SUPERSEDED}\n\n## Verified again\ny"
    document = f"# obelize fix\n\n| `{forged}` | 1 |\n\n## Limitations\n\ntail\n"
    once = report.superseded(document, record, "now")
    twice = report.superseded(once, record, "later")
    assert "tail" in once
    assert "tail" in twice
    assert twice.count(report.SUPERSEDED) == 2, "the forged one stays, and one real note"
    assert twice.count("checked this run again") == 1


def test_a_pack_s_text_that_is_the_note_marker_does_not_cut_the_report(quiet: Path) -> None:
    """A one-line message may be the HTML comment alone; only the note's own heading counts."""
    record = _record(quiet, _scan(quiet)).model_copy(
        update={"verify": VerifyRecord(status="not_run", reason="no_verify_commands")}
    )
    document = f"# obelize fix\n\n{report.SUPERSEDED}\n\n## Guidance\n\ntail\n"
    once = report.superseded(document, record, "now")
    twice = report.superseded(once, record, "later")
    assert "tail" in once
    assert twice.count("## Verified again") == 1
    assert twice.split("## Verified again")[0] == once.split("## Verified again")[0]


def test_a_printed_diff_is_redacted_and_the_file_is_not() -> None:
    """A terminal can be a CI log; the value of a secret-named variable goes, and a key shape."""
    key = "AIza" + "0" * 35
    patch = f" token_for_ci = '{'hunter2' * 2}'  # {key}\n".encode()
    shown = report.diff(patch, "f", {"CI_TOKEN": "hunter2" * 2})
    assert shown[0] == " token_for_ci = '[REDACTED:CI_TOKEN]'  # [REDACTED]"


def test_a_key_block_across_the_cut_is_redacted_whole() -> None:
    """The block spans lines, so the diff is redacted whole before any of it is cut."""
    block = "-----BEGIN RSA " + "PRIVATE KEY-----\nTk9UQVJFQUxLRVk=\n-----END RSA PRIVATE KEY-----"
    context = "".join(f" {line}\n" for line in block.split("\n"))
    shown = report.diff((" x\n" * 198 + context + " y\n").encode(), "f", {})
    assert " [REDACTED]" in shown
    assert not [row for row in shown if "Tk9U" in row or "BEGIN" in row]


def _withheld(*rows: tuple[str, int, str | None, str, tuple[str, ...] | None]) -> RunRecord:
    """Only `withheld` is read, so only it is built; a full record needs a whole run."""
    held = tuple(
        Withheld.model_validate(
            {"path": path, "line": line, "symbol": symbol, "bail": bail, "caused_by": caused}
        )
        for path, line, symbol, bail, caused in rows
    )
    return cast("RunRecord", SimpleNamespace(withheld=held))


NO_PINS = ManifestPlan()


def _pin(path: str = "requirements.txt") -> Finding:
    return Finding(
        path=path,
        line=1,
        column=0,
        kind="manifest",
        confidence_reason="manifest_dependency",
        symbol="acme-sdk",
        evidence=None,
        scan_status="needs_review",
        bail="repo_not_fully_migrated",
    )


def test_the_most_common_causes_are_named_and_the_files_they_held_are_not_counted_alone() -> None:
    record = _withheld(
        ("a.py", 3, "acme.sdk.Model", "model_object_escapes", None),
        ("a.py", 4, "acme.sdk.Model.run", "file_not_fully_migrated", ("model_object_escapes",)),
        ("a.py", 5, "acme.sdk.Model.run", "file_not_fully_migrated", ("model_object_escapes",)),
        ("b.py", 1, "acme.sdk", "local_import", None),
        ("requirements.txt", 1, "acme-sdk", "repo_not_fully_migrated", None),
    )
    held = ManifestPlan(findings=(_pin(),), blocking=("a.py",))
    lines = report._left(record, held, ".obelize/runs/x")
    assert lines[1] == (
        "5 finding(s) left for you. Most common reasons: model_object_escapes (3), "
        "local_import (1)."
    )
    assert lines[2:4] == [
        f"  model_object_escapes: {BAIL_ACTIONS['model_object_escapes']}",
        f"  local_import: {BAIL_ACTIONS['local_import']}",
    ]
    assert lines[4:6] == [
        "  a.py:3  acme.sdk.Model  model_object_escapes",
        "  b.py:1  acme.sdk  local_import",
    ]
    assert not [line for line in lines if "whole repository" in line]


def test_the_withheld_section_says_what_to_change_for_every_code_its_table_shows() -> None:
    record = _withheld(
        ("a.py", 3, "acme.sdk.Model", "model_object_escapes", None),
        ("a.py", 4, "acme.sdk.Model.run", "file_not_fully_migrated", ("model_object_escapes",)),
        ("b.py", 1, "acme.sdk", "local_import", None),
    )
    section = report._withheld_section(record)
    assert section[-7:] == [
        "",
        "What to change, by reason:",
        "",
        f"- `model_object_escapes`: {BAIL_ACTIONS['model_object_escapes']}",
        f"- `file_not_fully_migrated`: {BAIL_ACTIONS['file_not_fully_migrated']}",
        f"- `local_import`: {BAIL_ACTIONS['local_import']}",
        "",
    ]


def test_a_repository_held_only_by_atomicity_still_names_that() -> None:
    record = _withheld(("requirements.txt", 1, "acme-sdk", "repo_not_fully_migrated", None))
    lines = report._left(record, ManifestPlan(findings=(_pin(),), blocking=("a.py",)), "x")
    assert lines[1].endswith("Most common reasons: repo_not_fully_migrated (1).")
    assert lines[2] == f"  repo_not_fully_migrated: {BAIL_ACTIONS['repo_not_fully_migrated']}"


def test_only_five_causes_are_named_and_the_rest_are_counted() -> None:
    record = _withheld(*((f"m{n}.py", 1, "acme.sdk", "local_import", None) for n in range(7)))
    lines = report._left(record, NO_PINS, ".obelize/runs/x")
    assert len([line for line in lines if line.startswith("  m")]) == 5
    assert lines[8] == f"  and 2 more in {Path('.obelize/runs/x', 'REPORT.md')}"


def test_files_that_hold_the_pin_without_a_row_are_named_apart() -> None:
    record = _withheld(("a.py", 1, "acme.sdk", "local_import", None))
    held = ManifestPlan(blocking=("a.py", "analysis.ipynb"), transitive=("retry.py",))
    text = "\n".join(report._left(record, held, ".obelize/runs/x"))
    assert "Not analysed, so they hold the pin: analysis.ipynb." in text
    assert "a.py." not in text.split("Not analysed")[1]
    assert "declares: retry.py." in text


def test_a_file_importing_a_module_only_the_old_distribution_installed_is_not_unanalysed() -> None:
    record = _withheld(("a.py", 1, "acme.sdk", "local_import", None))
    held = ManifestPlan(blocking=("net.py",), transitive=("net.py",))
    text = "\n".join(report._left(record, held, ".obelize/runs/x"))
    assert "Not analysed" not in text
    assert "declares: net.py." in text


def test_a_declaration_the_pin_check_graded_twice_is_counted_once() -> None:
    legacy = _pin()
    new = Finding(**{**legacy.model_dump(), "symbol": "acme-client"})
    held = ManifestPlan(findings=(new, legacy), blocking=("a.py",))
    assert report._repository(held)[0].startswith("1 dependency declaration(s), blocked by 1 file")


def test_a_command_with_a_pipe_keeps_its_row_in_the_table() -> None:
    command = SimpleNamespace(
        command='sh -c "true | cat"',
        source="cli",
        status="pass",
        exit_code=0,
        duration_ms=3,
        log=None,
        truncated=False,
    )
    phase = SimpleNamespace(status="pass", reason=None, commands=(command,))
    row = report._phase_rows("After the patch", cast("VerifyRecord", phase))[-2]
    assert row.count("|") - row.count("\\|") == 7, row


def test_an_endpoint_that_said_nothing_has_a_dash_in_the_model_table() -> None:
    silent = SimpleNamespace(
        index=1, path="a.py", line=1, outcome="failed", failure=None, refusal=None, detail=None
    )
    model = SimpleNamespace(
        provider="p", model="m", host="h", proposals=0, accepted=0, tokens_in=0, tokens_out=0
    )
    row = report._model_section(cast("RunModel", model), [cast("ProposalRecord", silent)])[-2]
    assert row.endswith("| -- | -- |")


def test_what_an_endpoint_answered_is_one_escaped_line_in_the_model_table() -> None:
    proposal = SimpleNamespace(
        index=1,
        path="app.py",
        line=3,
        outcome="failed",
        failure="http_error",
        refusal=None,
        detail="HTTP 502\n<html><img src=https://t.example/p.png>\r\n| x |",
    )
    model = SimpleNamespace(
        provider="openai_compat",
        model="m",
        host="h",
        proposals=0,
        accepted=0,
        tokens_in=0,
        tokens_out=0,
    )
    row = report._model_section(cast("RunModel", model), [cast("ProposalRecord", proposal)])[-2]
    assert "\n" not in row
    assert not re.search(r"(?<!\\)[<>]", row), row
    assert row.count("|") - row.count("\\|") == 6, row


def test_a_pack_that_moves_a_whole_repository_says_so_for_its_source_rows_only() -> None:
    source = _withheld(
        ("a.py", 1, "openai.File", "flag_only_surface", None),
        ("b.py", 2, "openai.api_key", "repo_not_fully_migrated", None),
    )
    held = ManifestPlan(findings=(_pin(),), blocking=("a.py",))
    assert [line for line in report._left(source, held, "x") if "whole repository" in line]
    pin_only = _withheld(("requirements.txt", 1, "acme-sdk", "repo_not_fully_migrated", None))
    assert not [line for line in report._left(pin_only, held, "x") if "whole repository" in line]


def test_no_reason_is_given_where_nothing_was_held() -> None:
    assert report._left(_withheld(), NO_PINS, "x") == []


def test_the_link_to_what_the_codes_mean_points_at_the_heading_that_defines_them() -> None:
    page = Path(__file__).resolve().parents[2] / "docs" / "SCAN_VOCABULARY.md"
    anchor = report.CODES.rpartition("#")[2]
    slugs = {
        re.sub(r"[^a-z0-9 -]", "", line.lstrip("# ").lower()).replace(" ", "-")
        for line in page.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    }
    assert anchor in slugs


def test_a_warning_is_printed_for_an_edit_that_is_written_and_not_for_one_that_is_not() -> None:
    def edit(path: str, status: str, *codes: str) -> Edit:
        return Edit.model_validate(
            {
                "path": path,
                "line": 2 if status == "auto" else 3,
                "status": status,
                "rule_id": "r" if status == "auto" else None,
                "reason": None if status == "auto" else "local_import",
                "warnings": codes,
            }
        )

    plan = PlanDocument(
        obelize_version="0",
        edits=(
            edit("held.py", "auto", "history_parts_rewritten"),
            edit("held.py", "needs_review", "async_stream_await_preserved"),
            edit("kept.py", "auto", "model_name_looks_prefixed"),
        ),
    )
    meaning = WARNING_MEANINGS["model_name_looks_prefixed"]
    assert report._check(plan, {"kept.py"}) == [
        f"Check kept.py:2: model_name_looks_prefixed: {meaning}"
    ]
