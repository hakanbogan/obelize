"""What `run_dir` writes, and in what order: a `latest` that exists names a complete run.

Built from a real scan: a record projected from a hand-built `Scan` tests only the constructor.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from obelize import __version__, gitutil
from obelize.config import load as load_config
from obelize.evidence import report, run_dir
from obelize.evidence.folder import RunFolder
from obelize.models import (
    CommandResult,
    FileEdit,
    RunRecord,
    VerifyPhase,
    VerifyRecord,
    VerifyResult,
)
from obelize.packs import loader
from obelize.scan import runner
from obelize.verify import runner as verify_runner
from platforms import AS_ROOT, PYTHON, deny, junction, link, windows_only

BUNDLED = "gemini/google-generativeai-to-google-genai"
LOADED = loader.load(BUNDLED)

# `KEEP = [MODEL]` lets the model escape, so one group bails and `withheld[]` has a row.
LEGACY = """import google.generativeai as genai

genai.configure(api_key="k")
MODEL = genai.GenerativeModel("gemini-1.5-flash")
KEEP = [MODEL]
"""

# Fails to parse (a withheld row with no `symbol`); the import keeps it past the prefilter.
BROKEN = "import google.generativeai\n\ndef broken(:\n    pass\n"

MANIFEST = "google-generativeai==0.8.6\n"

WHEN = datetime(2026, 9, 18, 9, 14, 7, tzinfo=UTC)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(LEGACY, encoding="utf-8")
    (root / "broken.py").write_text(BROKEN, encoding="utf-8")
    (root / "requirements.txt").write_text(MANIFEST, encoding="utf-8")
    return root


@pytest.fixture
def scanned(tree: Path) -> runner.Scan:
    pack = loader.load(BUNDLED)
    return runner.scan(tree, load_config(tree).config, loader.to_scan_spec(pack), jobs=1)


def _record(scan: runner.Scan, tree: Path, **changes: object) -> RunRecord:
    pack = loader.load(BUNDLED)
    arguments: dict[str, object] = {
        "run_id": run_dir.new_id(WHEN, "3f9a1c72"),
        "scan": scan,
        "packs": [run_dir.Used(pack, scan.blocked[0] if scan.blocked else None)],
        "config": load_config(tree).config,
        "source": load_config(tree).source,
        "git": gitutil.state(tree),
        "argv": ("scan", "--repo", "."),
        "started": WHEN,
        "finished": WHEN + timedelta(seconds=1),
        "total_ms": 1234,
        "scan_ms": 1200,
    }
    arguments.update(changes)
    return run_dir.compose(**arguments)  # type: ignore[arg-type]


def test_the_run_id_is_the_published_pattern() -> None:
    assert run_dir.new_id(WHEN, "3f9a1c72") == "20260918T091407Z-3f9a1c72"
    assert RunRecord.model_fields["run_id"] is not None


def test_two_runs_started_in_the_same_second_are_still_two_runs() -> None:
    """The suffix is not a secret, so only its uniqueness and length are asserted."""
    ids = {run_dir.new_id(WHEN) for _ in range(32)}
    assert len(ids) == 32
    assert all(len(identifier.rsplit("-", 1)[1]) == run_dir.ENTROPY_BYTES * 2 for identifier in ids)


def test_the_clock_is_read_to_the_second_and_in_utc() -> None:
    moment = run_dir.now()
    assert moment.tzinfo is UTC
    assert moment.microsecond == 0
    assert run_dir.instant(moment).endswith("Z")


def test_an_id_the_pattern_refuses_cannot_reach_a_record(scanned: runner.Scan, tree: Path) -> None:
    with pytest.raises(ValueError, match="is not a run id"):
        _record(scanned, tree, run_id="2026-09-18T09:14:07Z-3f9a1c72")


def test_the_record_says_what_the_scan_found(scanned: runner.Scan, tree: Path) -> None:
    record = _record(scanned, tree)
    assert record.mode == "scan"
    assert record.exit_code == 0
    assert record.obelize_version == __version__
    assert record.counts.model_dump() == {
        **scanned.counts.model_dump(),
        "auto": 0,
        "warnings": 0,
    }
    assert [(pack.id, pack.source) for pack in record.packs] == [(BUNDLED, "bundled")]
    assert record.config.source == "defaults"
    assert record.timings.started_at == "2026-09-18T09:14:07Z"
    assert record.timings.finished_at == "2026-09-18T09:14:08Z"
    assert record.timings.total_ms == 1234
    assert record.timings.scan_ms == 1200


def test_the_four_fields_a_scan_cannot_fill_are_the_four_it_writes_empty(
    scanned: runner.Scan, tree: Path
) -> None:
    """Enforced by type, not default: a scan record claiming a verification cannot be built."""
    record = _record(scanned, tree)
    assert record.file_edits == ()
    assert record.idempotent is None
    assert record.verify is None
    assert record.model is None
    with pytest.raises(ValueError, match="verify"):
        RunRecord.model_validate({**record.model_dump(), "verify": {"status": "pass"}})


def test_every_withheld_finding_reaches_the_record_with_its_bail(
    scanned: runner.Scan, tree: Path
) -> None:
    """The bug report template asks only for `run.json`, so it must say what was refused and why."""
    record = _record(scanned, tree)
    refused = [finding for finding in scanned.findings if finding.scan_status != "eligible"]
    withheld = [finding for finding in refused if finding.bail is not None]
    assert withheld, "the tree was built so that something is withheld"
    assert [(row.path, row.line, row.bail) for row in record.withheld] == [
        (finding.path, finding.line, finding.bail) for finding in withheld
    ]


def test_the_one_withheld_row_with_no_symbol_is_the_refused_file(
    scanned: runner.Scan, tree: Path
) -> None:
    """A parse error has no symbol to name, yet `withheld[]` must still list it."""
    record = _record(scanned, tree)
    nameless = [row for row in record.withheld if row.symbol is None]
    assert [row.path for row in nameless] == ["broken.py"]
    assert nameless[0].bail == "input_does_not_parse"


def test_both_halves_of_limitations_arrive_in_one_sorted_list(
    scanned: runner.Scan, tree: Path
) -> None:
    record = _record(scanned, tree)
    assert [(row.path, row.code) for row in record.limitations] == [
        ("broken.py", "input_does_not_parse")
    ]
    assert len(record.limitations) == len(scanned.limitations) + len(scanned.skipped)


def test_the_two_halves_are_sorted_together_and_not_one_after_the_other(
    tree: Path, tmp_path: Path
) -> None:
    """Concatenating would put the walker's `z_link.py` first; the record must be byte-stable."""
    (tree / "z_link.py").symlink_to(tmp_path / "elsewhere.py")
    (tree / "a_broken.py").write_text(BROKEN, encoding="utf-8")
    pack = loader.load(BUNDLED)
    scan = runner.scan(tree, load_config(tree).config, loader.to_scan_spec(pack), jobs=1)
    assert scan.skipped, "the symlink is the walker's half"
    assert scan.limitations, "the refused parse is the reader's"
    record = _record(scan, tree)
    assert [(row.path, row.code) for row in record.limitations] == [
        ("a_broken.py", "input_does_not_parse"),
        ("broken.py", "input_does_not_parse"),
        ("z_link.py", "symlink"),
    ]


def test_a_repository_below_the_floor_is_blocked_and_still_reported(tree: Path) -> None:
    """`blocked` replaces the proposed migration, not the report."""
    (tree / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.9"\n', encoding="utf-8"
    )
    pack = loader.load(BUNDLED)
    scan = runner.scan(tree, load_config(tree).config, loader.to_scan_spec(pack), jobs=1)
    record = _record(scan, tree)
    assert [pack.blocked for pack in record.packs] == ["runtime_unsupported"]
    assert record.counts.findings == scan.counts.findings > 0


def test_a_repository_at_or_above_the_floor_is_not(tree: Path) -> None:
    """A declared floor the new distribution installs on records `null`."""
    (tree / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.10"\n', encoding="utf-8"
    )
    pack = loader.load(BUNDLED)
    scan = runner.scan(tree, load_config(tree).config, loader.to_scan_spec(pack), jobs=1)
    assert [pack.blocked for pack in _record(scan, tree).packs] == [None]


def test_the_record_validates_against_its_committed_schema(
    scanned: runner.Scan, tree: Path
) -> None:
    """`run.schema.json` is generated from this model, so the round trip stands in for it."""
    record = _record(scanned, tree)
    assert RunRecord.model_validate(json.loads(record.model_dump_json())) == record


def _write(scan: runner.Scan, tree: Path, record: RunRecord) -> run_dir.Written:
    return run_dir.write(tree, record, "{}\n", [LOADED], report.document(record, scan))


def test_the_five_artefacts_a_scan_writes_are_the_five_specified(
    scanned: runner.Scan, tree: Path
) -> None:
    """A scan has no plan, so `plan.json` and `patch.diff` are absent by design."""
    written = _write(scanned, tree, _record(scanned, tree))
    assert sorted(path.name for path in written.directory.iterdir()) == [
        "REPORT.md",
        "findings.json",
        "packs",
        "run.json",
    ]
    assert sorted(
        str(path.relative_to(written.directory / "packs"))
        for path in (written.directory / "packs").rglob("*")
        if path.is_file()
    ) == [f"{BUNDLED}/pack.sha256", f"{BUNDLED}/pack.yaml"]
    assert written.relative == f".obelize/runs/{written.run_id}"
    assert (tree / ".obelize" / "latest").read_text(encoding="utf-8") == f"{written.run_id}\n"


def test_the_artefacts_land_before_run_json_and_latest_lands_after_it(
    monkeypatch: pytest.MonkeyPatch, scanned: runner.Scan, tree: Path
) -> None:
    """The crash contract: a `latest` that exists always names a complete run."""
    order: list[str] = []
    text, binary = Path.write_text, Path.write_bytes

    def note_text(self: Path, *arguments: object, **keywords: object) -> int:
        order.append(self.name)
        return text(self, *arguments, **keywords)  # type: ignore[arg-type]

    def note_bytes(self: Path, *arguments: object, **keywords: object) -> int:
        order.append(self.name)
        return binary(self, *arguments, **keywords)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", note_text)
    monkeypatch.setattr(Path, "write_bytes", note_bytes)
    _write(scanned, tree, _record(scanned, tree))
    assert order == ["findings.json", "pack.yaml", "pack.sha256", "REPORT.md", "run.json", "latest"]


def test_the_hash_file_is_the_hash_the_record_names(scanned: runner.Scan, tree: Path) -> None:
    record = _record(scanned, tree)
    written = _write(scanned, tree, record)
    assert (written.directory / "packs" / BUNDLED / "pack.sha256").read_text(encoding="utf-8") == (
        f"{record.packs[0].sha256}\n"
    )


def test_the_findings_document_is_written_exactly_as_it_was_handed_over(
    scanned: runner.Scan, tree: Path
) -> None:
    """`findings.json` must equal `--json` byte for byte, so the writer takes a string."""
    record = _record(scanned, tree)
    body = '{"findings": []}\n'
    written = run_dir.write(tree, record, body, [LOADED], "# report\n")
    assert (written.directory / "findings.json").read_text(encoding="utf-8") == body


def test_the_second_run_does_not_collide_with_the_first(scanned: runner.Scan, tree: Path) -> None:
    first = _write(scanned, tree, _record(scanned, tree))
    second = _write(scanned, tree, _record(scanned, tree, run_id=run_dir.new_id(WHEN, "aaaaaaaa")))
    assert first.directory != second.directory
    assert (tree / ".obelize" / "latest").read_text(encoding="utf-8") == f"{second.run_id}\n"


def test_a_run_folder_is_never_written_twice(scanned: runner.Scan, tree: Path) -> None:
    """A repeated id would overwrite evidence; `exist_ok=False` refuses it."""
    record = _record(scanned, tree)
    _write(scanned, tree, record)
    with pytest.raises(run_dir.EvidenceError, match="could not be written"):
        _write(scanned, tree, record)


LINKS = [
    (".obelize", "is a symbolic link"),
    (".obelize/runs", "is a symbolic link"),
    (".obelize/latest", "is a symbolic link"),
]


@pytest.mark.parametrize(("where", "message"), LINKS, ids=[w for w, _ in LINKS])
def test_nothing_is_written_through_a_symbolic_link(
    scanned: runner.Scan, tree: Path, tmp_path: Path, where: str, message: str
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = tree / where
    target.parent.mkdir(parents=True, exist_ok=True)
    link(target, elsewhere if where != ".obelize/latest" else elsewhere / "pointer")
    with pytest.raises(run_dir.EvidenceError, match=message):
        _write(scanned, tree, _record(scanned, tree))


@pytest.mark.parametrize("where", [where for where, _ in LINKS])
def test_nothing_is_written_through_a_junction(
    scanned: runner.Scan, tree: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """Windows' answer, stubbed: `is_symlink` is false for a junction, `is_junction` is not."""
    monkeypatch.setattr(Path, "is_junction", lambda path: path.name == Path(where).name)
    with pytest.raises(run_dir.EvidenceError, match="is a symbolic link or a junction"):
        _write(scanned, tree, _record(scanned, tree))


@windows_only("POSIX has no junction; the stubbed answer above stands in for one")
@pytest.mark.parametrize("where", [".obelize", ".obelize/runs"])
def test_a_real_junction_is_not_written_through(
    scanned: runner.Scan, tree: Path, tmp_path: Path, where: str
) -> None:
    """Control: `is_symlink`, all the writer asked before, is false for it."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tree / where).parent.mkdir(parents=True, exist_ok=True)
    junction(tree / where, elsewhere)
    assert not (tree / where).is_symlink()
    with pytest.raises(run_dir.EvidenceError, match="is a symbolic link or a junction"):
        _write(scanned, tree, _record(scanned, tree))
    assert list(elsewhere.iterdir()) == []


@pytest.mark.skipif(AS_ROOT, reason="chmod means nothing to root")
def test_a_root_that_cannot_be_written_to_is_said_out_loud(
    scanned: runner.Scan, tree: Path
) -> None:
    """The message also says the scan completed, or a reader would blame the scan."""
    with (
        deny(tree, writes_only=True),
        pytest.raises(run_dir.EvidenceError, match="could not be created"),
    ):
        _write(scanned, tree, _record(scanned, tree))


@pytest.mark.skipif(AS_ROOT, reason="chmod means nothing to root")
def test_a_runs_directory_that_cannot_be_written_to_is_too(
    scanned: runner.Scan, tree: Path
) -> None:
    runs = tree / ".obelize" / "runs"
    runs.mkdir(parents=True)
    with (
        deny(runs, writes_only=True),
        pytest.raises(run_dir.EvidenceError, match="could not be written"),
    ):
        _write(scanned, tree, _record(scanned, tree))


@pytest.mark.skipif(AS_ROOT, reason="chmod means nothing to root")
def test_a_home_that_will_not_take_its_ignore_file_is_said_out_loud(
    scanned: runner.Scan, tree: Path
) -> None:
    home = tree / ".obelize"
    (home / "runs").mkdir(parents=True)
    with (
        deny(home, writes_only=True),
        pytest.raises(run_dir.EvidenceError, match=r"\.gitignore.*could not be written"),
    ):
        _write(scanned, tree, _record(scanned, tree))
    assert list((home / "runs").iterdir()) == [], "refused before the run folder was made"


def test_a_disk_that_will_not_take_the_ignore_file_is_said_out_loud_too(
    scanned: runner.Scan, tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full or read-only disk raises no permission error, and must not escape as a traceback."""

    def full(*arguments: object, **keywords: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(RunFolder, "write", full)
    with pytest.raises(run_dir.EvidenceError, match=r"\.gitignore could not be written: No space"):
        _write(scanned, tree, _record(scanned, tree))


# Refusals no corpus can pose: a caller handing the writer two statements that disagree.

DRY_RUN = VerifyRecord(status="not_run", reason="dry_run")


def _verified(**changes: object) -> run_dir.Verified:
    arguments: dict[str, object] = {"record": DRY_RUN}
    arguments.update(changes)
    return run_dir.Verified(**arguments)  # type: ignore[arg-type]


def _artefacts(**changes: object) -> run_dir.Artefacts:
    arguments: dict[str, object] = {"plan": "{}\n", "patch": b"", "verify": _verified()}
    arguments.update(changes)
    return run_dir.Artefacts(**arguments)  # type: ignore[arg-type]


def _as_fix(record: RunRecord, **changes: object) -> RunRecord:
    """`record` in plan mode, with the fields that mode changes."""
    counts = {**record.counts.model_dump(), "eligible": 0, "auto": record.counts.eligible}
    return RunRecord.model_validate(
        {
            **record.model_dump(),
            "mode": "plan",
            "counts": counts,
            "verify": DRY_RUN.model_dump(),
            "timings": {**record.timings.model_dump(), "plan_ms": 5},
            **changes,
        }
    )


def test_a_scan_handed_a_plan_and_a_plan_handed_none_are_both_refused(
    scanned: runner.Scan, tree: Path
) -> None:
    """If the index and the folder disagree, a reader cannot tell which is wrong."""
    record = _record(scanned, tree)
    with pytest.raises(run_dir.EvidenceError, match="no plan and no patch"):
        run_dir.write(tree, record, "{}\n", [LOADED], "doc", _artefacts())
    with pytest.raises(run_dir.EvidenceError, match="a plan and a patch"):
        run_dir.write(tree, _as_fix(record), "{}\n", [LOADED], "doc")
    assert not (tree / ".obelize").exists(), "nothing is created before the two agree"


def test_a_snapshot_the_index_does_not_name_is_refused(scanned: runner.Scan, tree: Path) -> None:
    """An unindexed snapshot is unreachable; an indexed one that is missing breaks a revert."""
    edit = FileEdit(
        path="app.py",
        before_sha256="a" * 64,
        after_sha256="b" * 64,
        hunks=1,
        rules=("rename-import",),
    )
    record = _as_fix(
        _record(scanned, tree),
        mode="apply",
        file_edits=[edit.model_dump()],
        idempotent=False,
        verify=VerifyRecord(status="not_run", reason="no_changes_to_verify").model_dump(),
        timings={
            **_record(scanned, tree).timings.model_dump(),
            "plan_ms": 5,
            "apply_ms": 5,
        },
    )
    verify = _verified(record=VerifyRecord(status="not_run", reason="no_changes_to_verify"))
    with pytest.raises(run_dir.EvidenceError, match="describe different files"):
        run_dir.write(tree, record, "{}\n", [LOADED], "doc", _artefacts(verify=verify))
    stray = (("snapshots/before/" + "a" * 64, b"x"), ("snapshots/after/" + "c" * 64, b"y"))
    with pytest.raises(run_dir.EvidenceError, match="describe different files"):
        run_dir.write(
            tree, record, "{}\n", [LOADED], "doc", _artefacts(verify=verify, snapshots=stray)
        )


def test_the_verification_written_twice_has_to_be_the_same_one(
    scanned: runner.Scan, tree: Path
) -> None:
    """`verify/verify.json` duplicates the record's verification, so the two must match."""
    record = _as_fix(_record(scanned, tree))
    other = _verified(record=VerifyRecord(status="not_run", reason="no_changes_to_verify"))
    with pytest.raises(run_dir.EvidenceError, match="not the same one"):
        run_dir.write(tree, record, "{}\n", [LOADED], "doc", _artefacts(verify=other))


def _passed(**changes: object) -> CommandResult:
    arguments: dict[str, object] = {
        "command": "pytest -q",
        "source": "cli",
        "status": "pass",
        "exit_code": 0,
        "duration_ms": 3,
        "output": "ok\n",
    }
    arguments.update(changes)
    return CommandResult(**arguments)


def test_a_junit_report_reaches_the_folder_under_the_phase_that_produced_it() -> None:
    """Each phase numbers its reports from 1, so only the phase directory keeps them apart."""
    result = VerifyResult(
        status="pass",
        commands=(_passed(junit="1.junit.xml"),),
        baseline=VerifyPhase(status="pass", commands=(_passed(junit="1.junit.xml"),)),
    )
    verified = run_dir.verification(
        result,
        after_junit={"1.junit.xml": b"<after/>"},
        baseline_junit={"1.junit.xml": b"<baseline/>"},
    )
    assert dict(verified.files) == {
        "verify/baseline/1.log": b"ok\n",
        "verify/baseline/1.junit.xml": b"<baseline/>",
        "verify/after/1.log": b"ok\n",
        "verify/after/1.junit.xml": b"<after/>",
    }
    assert verified.record.commands[0].junit == "verify/after/1.junit.xml"
    assert verified.record.baseline is not None
    assert verified.record.baseline.commands[0].junit == "verify/baseline/1.junit.xml"
    assert verified.ran is True


def test_a_junit_row_with_no_bytes_behind_it_is_refused() -> None:
    """A row pointing at a missing file is worse than no row."""
    result = VerifyResult(status="pass", commands=(_passed(junit="1.junit.xml"),))
    with pytest.raises(run_dir.EvidenceError, match="bytes were not passed in"):
        run_dir.verification(result)


def test_a_verification_nothing_ran_under_writes_no_directory() -> None:
    verified = run_dir.verification(VerifyResult(status="not_run", reason="dry_run"))
    assert verified.files == ()
    assert verified.ran is False


def test_a_command_that_printed_nothing_gets_no_log_file() -> None:
    """An empty log file reads as lost output; `log: null` says there was none."""
    verified = run_dir.verification(VerifyResult(status="pass", commands=(_passed(output=""),)))
    assert verified.files == ()
    assert verified.record.commands[0].log is None
    assert verified.ran is True


def test_a_fix_writes_its_artefacts_before_run_json_too(
    monkeypatch: pytest.MonkeyPatch, scanned: runner.Scan, tree: Path
) -> None:
    """A `run.json` written before the snapshots would index files that may not exist."""
    order: list[str] = []
    text, binary = Path.write_text, Path.write_bytes

    def note_text(self: Path, *arguments: object, **keywords: object) -> int:
        order.append(self.name)
        return text(self, *arguments, **keywords)  # type: ignore[arg-type]

    def note_bytes(self: Path, *arguments: object, **keywords: object) -> int:
        order.append(self.name)
        return binary(self, *arguments, **keywords)  # type: ignore[arg-type]

    verified = run_dir.verification(VerifyResult(status="pass", commands=(_passed(),)))
    written = FileEdit(
        path="app.py",
        before_sha256="a" * 64,
        after_sha256="b" * 64,
        hunks=1,
        rules=("rename-import",),
    )
    base = _record(scanned, tree)
    record = _as_fix(
        base,
        mode="apply",
        file_edits=[written.model_dump()],
        idempotent=False,
        verify=verified.record.model_dump(),
        timings={
            **base.timings.model_dump(),
            "plan_ms": 5,
            "apply_ms": 5,
            "verify_ms": 5,
        },
    )
    monkeypatch.setattr(Path, "write_text", note_text)
    monkeypatch.setattr(Path, "write_bytes", note_bytes)
    run_dir.write(
        tree,
        record,
        "{}\n",
        [LOADED],
        "# report\n",
        _artefacts(
            verify=verified,
            snapshots=(
                ("snapshots/before/" + "a" * 64, b"x"),
                ("snapshots/after/" + "b" * 64, b"y"),
            ),
        ),
    )
    assert order[-2:] == ["run.json", "latest"]
    assert set(order[:-2]) == {
        "findings.json",
        "pack.yaml",
        "pack.sha256",
        "REPORT.md",
        "plan.json",
        "patch.diff",
        "a" * 64,
        "b" * 64,
        "1.log",
        "verify.json",
    }


def test_the_index_and_the_model_directory_have_to_agree(scanned: runner.Scan, tree: Path) -> None:
    record = _as_fix(_record(scanned, tree))
    with pytest.raises(run_dir.EvidenceError, match="records no model"):
        run_dir.write(
            tree,
            record,
            "{}\n",
            [LOADED],
            "doc",
            _artefacts(model=(("model/model.json", b"{}\n"),)),
        )
    consulted = _as_fix(
        _record(scanned, tree),
        model={
            "provider": "openai_compat",
            "host": "localhost",
            "model": "qwen2.5-coder",
            "proposals": 0,
            "accepted": 0,
            "tokens_in": 0,
            "tokens_out": 0,
        },
        timings={**_record(scanned, tree).timings.model_dump(), "plan_ms": 5, "model_ms": 7},
    )
    with pytest.raises(run_dir.EvidenceError, match="records a model"):
        run_dir.write(tree, consulted, "{}\n", [LOADED], "doc", _artefacts())
    assert not (tree / ".obelize").exists(), "nothing is created before the two agree"


def test_a_log_that_is_not_utf_8_is_written_byte_for_byte(tmp_path: Path) -> None:
    printed = b"caf\xe9\n"
    result = verify_runner.execute(
        tmp_path,
        verify_runner.Command.of(
            f'{PYTHON} -c "import sys; sys.stdout.buffer.write({printed!r})"', "cli"
        ),
        timeout_s=30,
        environ=dict(os.environ),
    )
    verified = run_dir.verification(VerifyResult(status="pass", commands=(result,)))
    assert dict(verified.files) == {"verify/after/1.log": printed}
