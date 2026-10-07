"""The terminal summary and `REPORT.md`: the claims a reader relies on, not their wording.

Empty sections are asserted too, since silence looks like a scan that never ran; trees are real
so the renderer never agrees with a value no pass produces.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from obelize import gitutil
from obelize.config import load as load_config
from obelize.evidence import report, run_dir
from obelize.models import PackRef, PlanDocument, RunRecord, UndoFile, UndoRecord, VerifyRecord
from obelize.packs import loader
from obelize.scan import runner, runtime

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
        "Columns: line, kind, symbol, status, reason. eligible: obelize fix will try to migrate "
        "it; needs_review: left for you, for the reason shown; unsupported: the new SDK has no "
        "equivalent; not_a_usage: shown for context only."
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


@pytest.mark.parametrize(
    ("blocked", "says"),
    [
        (
            runtime.Blocked("runtime_unsupported", "new-sdk", "pyproject.toml", ">=3.8", ">=3.10"),
            "pyproject.toml declares Python >=3.8, which allows versions new-sdk does not install "
            "on, so this run reports its findings and plans no change. To migrate, raise the "
            "minimum in pyproject.toml to >=3.10 and run again.",
        ),
        (
            runtime.Blocked(
                "legacy_version_unsupported", "old-sdk", "requirements.txt", ">=1", ">=3"
            ),
            "requirements.txt declares old-sdk >=1, which allows versions this migration does "
            "not cover, so this run reports its findings and plans no change. To migrate, pin "
            "old-sdk to >=3 in requirements.txt and run again.",
        ),
        (
            runtime.Blocked("legacy_version_unsupported", "old-sdk", "requirements.txt", "", ">=3"),
            "requirements.txt declares old-sdk with no version, which allows versions this "
            "migration does not cover, so this run reports its findings and plans no change. To "
            "migrate, pin old-sdk to >=3 in requirements.txt and run again.",
        ),
        (
            runtime.Blocked("legacy_version_unsupported", "old-sdk", "pyproject.toml", None, ">=3"),
            "pyproject.toml declares old-sdk in a form obelize cannot read, so this run reports "
            "its findings and plans no change. To migrate, write it as a plain requirement such "
            "as old-sdk>=3 in pyproject.toml and run again.",
        ),
        (
            runtime.Blocked("legacy_version_unsupported", "old-sdk", "", None, ">=3"),
            "No manifest declares old-sdk, so the version in use is not known and this run "
            "reports its findings and plans no change. To migrate, declare old-sdk >=3 in a "
            "manifest obelize reads and run again.",
        ),
    ],
    ids=["python", "pinned-below", "unpinned", "unreadable", "undeclared"],
)
def test_a_blocked_run_names_the_declaration_and_what_would_unblock_it(
    blocked: runtime.Blocked, says: str
) -> None:
    assert report._blocked(blocked, report._bare) == says


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
    assert "- `requirements.txt`:1 `google-generativeai`: not_a_usage" in text
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
