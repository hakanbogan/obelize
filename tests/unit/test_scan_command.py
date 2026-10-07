"""`obelize scan`: the flags, the two documents and the four exit codes.

Only the surface `docs/CLI.md` publishes; `tests/oracle/` grades the scan itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from obelize import __version__
from obelize.cli import app
from obelize.evidence import run_dir
from obelize.models import EXIT_CODES, FindingsDocument
from obelize.native import processes
from obelize.packs import loader
from obelize.scan import runner as scanner
from platforms import posix_only, stdout_as_on_windows, text_files_as_on_windows, windows_only

GEMINI = "gemini/google-generativeai-to-google-genai"

runner = CliRunner()

LEGACY = """import google.generativeai as genai

genai.configure(api_key="k")
MODEL = genai.GenerativeModel("gemini-1.5-flash")
KEEP = [MODEL]
"""

PLAIN = "def add(left: int, right: int) -> int:\n    return left + right\n"

MANIFEST = "google-generativeai==0.8.6\n"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(LEGACY, encoding="utf-8")
    (root / "plain.py").write_text(PLAIN, encoding="utf-8")
    (root / "requirements.txt").write_text(MANIFEST, encoding="utf-8")
    return root


def _scan(tree: Path, *extra: str) -> Result:
    return runner.invoke(app, ["scan", "--repo", str(tree), *extra])


def _folder(tree: Path) -> Path:
    latest = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    return tree / ".obelize" / "runs" / latest


def test_the_default_pack_is_one_that_ships() -> None:
    """`DEFAULT_PACK` is a literal, so renaming the bundled pack must fail here, not for a user."""
    assert GEMINI in loader.bundled_ids()


def test_json_is_the_findings_document_and_nothing_else(tree: Path) -> None:
    result = _scan(tree, "--json")
    assert result.exit_code == 0
    document = FindingsDocument.model_validate_json(result.stdout)
    assert document.obelize_version == __version__
    assert [pack.id for pack in document.packs] == [GEMINI]
    assert document.counts.findings == len(document.findings) > 0


def test_two_runs_over_the_same_input_are_byte_identical(tree: Path) -> None:
    """The first run's `.obelize/` folder is always excluded, so the second does not scan it."""
    first = _scan(tree, "--json")
    second = _scan(tree, "--json")
    assert first.stdout_bytes == second.stdout_bytes
    assert "obelize/runs" not in first.stdout


def test_the_worker_count_changes_the_runtime_and_not_the_answer(tree: Path) -> None:
    one = _scan(tree, "--json", "--jobs", "1")
    many = _scan(tree, "--json", "--jobs", "4")
    assert one.stdout_bytes == many.stdout_bytes


def test_the_worker_count_asked_for_is_the_one_that_ran(tree: Path) -> None:
    """Only REPORT.md shows it: `findings.json` is byte-identical, `run.json` has a fixed schema."""
    _scan(tree, "--jobs", "4")
    assert "4 worker process(es)" in (_folder(tree) / "REPORT.md").read_text(encoding="utf-8")


def test_a_worker_count_below_one_is_refused_before_a_file_is_read(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object, **_keywords: object) -> object:
        raise AssertionError("the scan started with an unusable --jobs")

    monkeypatch.setattr(scanner, "scan", refuse)
    result = _scan(tree, "--jobs", "0")
    assert result.exit_code == 2
    assert "--jobs must be at least 1, got 0" in result.output


def test_a_worker_count_above_the_pool_limit_is_refused_before_a_file_is_read(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' limit, stubbed small, since the real one is only reached there."""

    def refuse(*_args: object, **_keywords: object) -> object:
        raise AssertionError("the scan started with an unusable --jobs")

    monkeypatch.setattr(processes, "WORKER_LIMIT", 2)
    monkeypatch.setattr(scanner, "scan", refuse)
    result = _scan(tree, "--jobs", "3")
    assert result.exit_code == 2
    assert "at most 2" in result.output


@windows_only("POSIX's pool has no limit; the stubbed limit above shows the refusal there")
def test_a_worker_count_windows_cannot_pool_is_a_usage_error(tree: Path) -> None:
    """Control: the pool itself refuses 62 workers with a `ValueError` and takes 61."""
    with pytest.raises(ValueError, match="61"):
        ProcessPoolExecutor(max_workers=62)
    ProcessPoolExecutor(max_workers=61).shutdown()
    result = _scan(tree, "--jobs", "62")
    assert result.exit_code == 2
    assert "at most 61" in result.output


def test_the_findings_in_the_run_folder_are_the_bytes_that_were_printed(tree: Path) -> None:
    result = _scan(tree, "--json")
    assert (_folder(tree) / "findings.json").read_bytes() == result.stdout_bytes


def test_the_evidence_is_the_same_bytes_where_text_files_end_lines_with_crlf(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows text mode writes each `\\n` as CRLF, so the run folder is written as bytes."""
    text_files_as_on_windows(monkeypatch)
    result = _scan(tree, "--json")
    assert result.exit_code == 0, result.output
    folder = _folder(tree)
    written = [path for path in folder.rglob("*") if path.is_file()]
    assert [path.name for path in written if b"\r" in path.read_bytes()] == []
    assert (tree / ".obelize" / "latest").read_bytes() == f"{folder.name}\n".encode()
    assert (folder / "findings.json").read_bytes() == result.stdout_bytes


def test_json_is_utf8_bytes_whatever_the_output_stream_encodes(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A redirected Windows stdout is cp1252 with CRLF line ends, and cp1252 has no `ğ`."""
    (tree / "sağ.py").write_text(LEGACY, encoding="utf-8", newline="\n")
    reached = stdout_as_on_windows(monkeypatch)
    app(["scan", "--repo", str(tree), "--json"], standalone_mode=False)
    assert reached.getvalue() == (_folder(tree) / "findings.json").read_bytes()
    assert "sağ.py" in {row["path"] for row in json.loads(reached.getvalue())["findings"]}


@windows_only("a POSIX pipe keeps LF; stdout_as_on_windows gives the tests above a Windows pipe")
def test_a_redirected_json_scan_is_utf8_with_no_carriage_return(tree: Path) -> None:
    """Control: `print` to the same kind of pipe ends its line with CRLF."""
    utf8 = {"PYTHONIOENCODING", "PYTHONUTF8"}
    ansi = {name: value for name, value in os.environ.items() if name not in utf8}
    control = subprocess.run(
        [sys.executable, "-c", "print('a')"], capture_output=True, check=True, env=ansi
    )
    assert control.stdout == b"a\r\n"
    (tree / "sağ.py").write_bytes(LEGACY.encode("utf-8"))
    completed = subprocess.run(
        [sys.executable, "-m", "obelize.cli", "scan", "--repo", str(tree), "--json"],
        capture_output=True,
        check=False,
        env=ansi,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == (_folder(tree) / "findings.json").read_bytes()
    assert b"\r" not in completed.stdout
    assert "sağ.py" in completed.stdout.decode("utf-8")


def test_a_json_run_says_where_the_evidence_went_without_saying_it_on_stdout(
    tree: Path,
) -> None:
    """`verify --run <id>` needs the id, and stdout must stay pure JSON, so it goes to stderr."""
    result = _scan(tree, "--json")
    assert f"Evidence: {_folder(tree)}" in result.stderr
    assert "Evidence" not in result.stdout
    assert result.stdout_bytes == (_folder(tree) / "findings.json").read_bytes()


def test_the_table_names_every_file_the_findings_are_in(tree: Path) -> None:
    result = _scan(tree)
    assert result.exit_code == 0
    assert "  app.py" in result.stdout
    assert "  requirements.txt" in result.stdout
    assert f"Evidence: {_folder(tree)}" in result.stdout
    assert "plain.py" not in result.stdout, "nothing was found in it"


@pytest.mark.parametrize("extra", [(), ("--json",)], ids=["table", "json"])
def test_the_evidence_path_opens_from_where_the_scan_ran(
    tree: Path, monkeypatch: pytest.MonkeyPatch, extra: tuple[str, ...]
) -> None:
    monkeypatch.chdir(tree.parent)
    result = runner.invoke(app, ["scan", "--repo", "repo", *extra])
    (line,) = [one for one in result.output.splitlines() if one.startswith("Evidence: ")]
    assert line == f"Evidence: {Path('repo', '.obelize', 'runs', _folder(tree).name)}"
    assert Path(line.removeprefix("Evidence: ")).is_dir()


def test_a_scan_of_the_current_directory_names_its_folder_as_it_is(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tree)
    result = runner.invoke(app, ["scan"])
    named = Path(".obelize", "runs", _folder(tree).name)
    assert f"Evidence: {named}" in result.stdout.splitlines()


def test_list_files_prints_the_selection_and_stops(tree: Path) -> None:
    result = _scan(tree, "--list-files")
    assert result.exit_code == 0
    assert result.stdout.split() == ["app.py", "plain.py"]
    assert not (tree / ".obelize").exists(), "it stopped, so there is nothing to record"


def test_list_files_reads_the_exclusions_and_not_the_files(tree: Path) -> None:
    (tree / ".obelize.yml").write_text('exclude:\n  - "plain.py"\n', encoding="utf-8")
    (tree / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    result = _scan(tree, "--list-files")
    assert result.exit_code == 0
    assert result.stdout.split() == ["app.py", "broken.py"]


def test_the_run_folder_records_the_run(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["obelize", "scan", "--repo", "."])
    _scan(tree)
    record = json.loads((_folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert record["mode"] == "scan"
    assert record["exit_code"] == 0
    assert record["argv"] == ["scan", "--repo", "."]
    assert [pack["source"] for pack in record["packs"]] == ["bundled"]
    assert record["config"]["source"] == "defaults"
    assert record["timings"]["scan_ms"] >= 0
    assert record["withheld"], "the model escapes, so something is withheld"


def test_the_configuration_the_record_names_is_the_one_that_was_used(tree: Path) -> None:
    (tree / ".obelize.yml").write_text(
        'include: "**/*.py"\nexclude:\n  - "plain.py"\nmax_file_bytes: 4096\n', encoding="utf-8"
    )
    _scan(tree)
    record = json.loads((_folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert record["config"] == {
        "source": "file",
        "include": "**/*.py",
        "exclude": ["plain.py"],
        "max_file_bytes": 4096,
    }


def test_every_artefact_a_scan_writes_is_there(tree: Path) -> None:
    _scan(tree)
    folder = _folder(tree)
    assert sorted(path.name for path in folder.iterdir()) == [
        "REPORT.md",
        "findings.json",
        "packs",
        "run.json",
    ]
    assert folder.joinpath("packs", GEMINI, "pack.yaml").read_bytes() == loader.load(GEMINI).data


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t.invalid", *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_a_scan_leaves_git_nothing_to_add(tree: Path) -> None:
    """A run folder holds copies of the source and what commands printed: never `git add -A`'s."""
    _git(tree, "init", "-q")
    _git(tree, "add", "-A")
    _git(tree, "-c", "commit.gpgsign=false", "commit", "-qm", "before")
    assert _scan(tree).exit_code == 0
    assert _folder(tree).is_dir()
    assert _git(tree, "status", "--porcelain", "--untracked-files=all") == ""


@pytest.mark.parametrize("shape", ["file", "link"])
def test_an_ignore_file_already_there_is_left_as_it_is(
    tree: Path, tmp_path: Path, shape: str
) -> None:
    """Somebody's own rules stay; writing to a link would follow it out of the repository."""
    home = tree / ".obelize"
    home.mkdir()
    ignore = home / ".gitignore"
    elsewhere = tmp_path / "elsewhere"
    if shape == "file":
        ignore.write_text("runs/\n", encoding="utf-8")
    else:
        ignore.symlink_to(elsewhere)
    assert _scan(tree).exit_code == 0
    if shape == "file":
        assert ignore.read_text(encoding="utf-8") == "runs/\n"
    else:
        assert ignore.is_symlink()
        assert not elsewhere.exists()


def test_a_run_folder_that_cannot_be_written_is_not_a_silent_success(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit `1`, and the message blames the evidence write, not the scan."""

    def refuse(*_args: object, **_keywords: object) -> object:
        raise run_dir.EvidenceError("the run folder could not be written: no")

    monkeypatch.setattr(run_dir, "write", refuse)
    result = _scan(tree, "--json")
    assert result.exit_code == 1
    assert "could not be written" in result.output
    assert '"obelize_version"' not in result.stdout, (
        "the evidence is written before the answer is printed"
    )


def test_a_scan_that_finds_nothing_still_succeeds(tmp_path: Path) -> None:
    """`0` with or without findings: a scan is not a test suite."""
    (tmp_path / "plain.py").write_text(PLAIN, encoding="utf-8")
    result = _scan(tmp_path, "--json")
    assert result.exit_code == 0
    assert FindingsDocument.model_validate_json(result.stdout).findings == ()


def test_a_pack_that_is_not_valid_exits_seven(tree: Path, tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("id: nope\n", encoding="utf-8")
    result = _scan(tree, "--pack", str(broken))
    assert result.exit_code == 7
    assert "is not a valid pack" in result.output


def test_a_pack_that_is_not_there_exits_two(tree: Path, tmp_path: Path) -> None:
    """Nothing to read is a usage error, the same class as a misspelled flag."""
    result = _scan(tree, "--pack", str(tmp_path / "absent.yaml"))
    assert result.exit_code == 2
    assert "no pack at" in result.output


def test_a_bundled_pack_that_does_not_validate_is_an_obelize_defect(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`1`, not `7`: the invalid input is obelize's own, not the user's."""

    def refuse(reference: str, root: Path | None = None, dirs: object = ()) -> object:
        raise loader.PackInvalidError(reference, ["id: Field required"], bundled=True)

    monkeypatch.setattr(loader, "load", refuse)
    result = _scan(tree)
    assert result.exit_code == 1
    assert "a bug in obelize" in result.output


USAGE = [
    # Names the flag, not just the path, so a CI log says what to retype.
    (["scan", "--repo", "nowhere"], "--repo nowhere is not a directory"),
    (["scan", "--jobs", "0"], "--jobs must be at least 1"),
    (["scan", "--nope"], "No such option"),
]


@pytest.mark.parametrize(("argv", "message"), USAGE, ids=["no-such-root", "jobs-0", "no-such-flag"])
def test_a_usage_error_exits_two(argv: list[str], message: str) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 2
    assert message in result.output


def test_a_configuration_that_cannot_be_used_exits_two(tree: Path) -> None:
    """`docs/CLI.md` classes a bad `.obelize.yml` with a misspelled flag: `2`, before any read."""
    (tree / ".obelize.yml").write_text("nonsense: true\n", encoding="utf-8")
    result = _scan(tree)
    assert result.exit_code == 2
    assert "nonsense" in result.output


def test_every_exit_code_the_command_can_return_is_in_the_published_set() -> None:
    """Guards the tests above, not the command: `EXIT_CODES` is the set `docs/CLI.md` closes."""
    assert {0, 1, 2, 7} <= EXIT_CODES


def test_the_installed_command_records_the_arguments_it_was_given(tree: Path) -> None:
    """`argv` makes `--trust-repo-config` auditable; only a real subprocess shows what it got."""
    completed = subprocess.run(
        [sys.executable, "-m", "obelize.cli", "scan", "--repo", str(tree), "--jobs", "1"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    record = json.loads((_folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert record["argv"] == ["scan", "--repo", str(tree), "--jobs", "1"]


@posix_only("a Windows name cannot hold a backslash")
def test_an_unusable_name_is_a_limitation_that_quotes_it_and_names_no_path(tree: Path) -> None:
    """A `run.json` path is a repository path, and this one is not."""
    (tree / "weird\\name.py").write_bytes(b"x = 1\n")
    result = _scan(tree)
    assert result.exit_code == 0, result.output
    record = json.loads((_folder(tree) / "run.json").read_text(encoding="utf-8"))
    (row,) = [row for row in record["limitations"] if row["code"] == "unusable_name"]
    assert row["path"] is None
    assert row["detail"].startswith("weird\\name.py: The name is not valid UTF-8")


@posix_only("a Windows name cannot hold a backslash")
def test_a_directory_with_an_unusable_name_outside_git_is_a_limitation_too(tree: Path) -> None:
    """The fallback walk meets the directory itself, which git never lists."""
    (tree / "weird\\dir").mkdir()
    (tree / "weird\\dir" / "app.py").write_text(LEGACY, encoding="utf-8")
    result = _scan(tree)
    assert result.exit_code == 0, result.output
    record = json.loads((_folder(tree) / "run.json").read_text(encoding="utf-8"))
    (row,) = [row for row in record["limitations"] if row["code"] == "unusable_name"]
    assert row["path"] is None
    assert row["detail"].startswith("weird\\dir: The name is not valid UTF-8")
