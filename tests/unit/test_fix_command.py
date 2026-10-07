"""`obelize fix`: the published flags and the failures a corpus cannot stage.

Exit codes and phase order are graded in tests/oracle/test_commands_against_the_oracle.py.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from obelize import cli, commands, gitutil
from obelize.cli import app
from obelize.commands import CommandError
from obelize.evidence import report, run_dir
from obelize.native import shell, windows_programs
from obelize.verify import runner as verifier
from platforms import (
    AS_ROOT,
    PYTHON,
    SHEBANG,
    copied,
    deny,
    link,
    posix_only,
    quoted,
    reports_held_as_on_windows,
    stdout_as_on_windows,
    text_files_as_on_windows,
    windows_only,
)

runner = CliRunner()

PACK = "gemini/google-generativeai-to-google-genai"

LEGACY = """import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
"""


# Three findings held back by one model that escapes, two of them only because the file cannot
# be half-migrated, and one earlier finding held back for a mention mocked by name.
ESCAPING = """import google.generativeai as genai

genai.configure(api_key="k")
MODEL = genai.GenerativeModel("gemini-1.5-flash")
KEEP = [MODEL]
"""
MOCKED = (
    'from unittest import mock\n\nPATCHED = mock.patch("google.generativeai.GenerativeModel")\n'
)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(LEGACY, encoding="utf-8", newline="\n")
    (root / "requirements.txt").write_text(
        "google-generativeai==0.8.6\n", encoding="utf-8", newline="\n"
    )
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "work"], check=True)
    for key, value in (("user.name", "t"), ("user.email", "t@t.invalid")):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", "commit", "-qm", "before"],
        check=True,
    )
    return root


def fix(tree: Path, *extra: str) -> Result:
    return runner.invoke(app, ["fix", "--repo", str(tree), "--pack", PACK, *extra])


def folder(tree: Path) -> Path:
    run_id = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    return tree / ".obelize" / "runs" / run_id


def test_without_a_pack_the_bundled_one_is_used_as_scan_uses_it(tree: Path) -> None:
    result = runner.invoke(app, ["fix", "--repo", str(tree)])
    assert result.exit_code == 0, result.output
    record = json.loads((folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert [pack["id"] for pack in record["packs"]] == [PACK]


def test_a_pack_with_nothing_behind_it_is_a_usage_error(tree: Path) -> None:
    assert fix(tree, "--pack", "./nowhere.yaml").exit_code == 2


def test_a_pack_that_is_not_one_exits_seven(tree: Path) -> None:
    """The same code `scan` and `pack validate` use."""
    broken = tree.parent / "broken.yaml"
    broken.write_text("pack_version: nope\n", encoding="utf-8")
    result = runner.invoke(app, ["fix", "--repo", str(tree), "--pack", str(broken)])
    assert result.exit_code == 7


def test_a_repo_that_is_not_a_directory_is_a_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["fix", "--repo", str(tmp_path / "gone"), "--pack", PACK])
    assert result.exit_code == 2
    assert "is not a directory" in result.output


def test_a_timeout_below_one_second_is_refused_by_the_flag(tree: Path) -> None:
    """Refused at the flag, before a repository is opened, not as an error from the merge."""
    assert fix(tree, "--timeout", "0").exit_code == 2


def test_an_allowlist_entry_that_cannot_run_is_a_usage_error(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user's file is read with its model block, before the scan writes a run folder."""
    home = tmp_path / "home"
    (home / "obelize").mkdir(parents=True)
    (home / "obelize" / "config.yml").write_text(
        "verify:\n  allow:\n    - 'pytest | tee log'\n", encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    result = fix(tree, "--apply")
    assert result.exit_code == 2, result.output
    assert "runs without a shell" in result.output
    assert not (tree / ".obelize").exists()


def test_json_writes_the_plan_document_and_the_evidence_path_goes_to_stderr(
    tree: Path,
) -> None:
    """As with `scan --json`, stdout is the document and nothing else."""
    result = fix(tree, "--json")
    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert [row["path"] for row in document["files"]] == ["app.py", "requirements.txt"]
    assert result.stdout_bytes == (folder(tree) / "plan.json").read_bytes()
    assert f"Evidence: {folder(tree)}" in result.stderr


def test_the_plan_and_the_record_are_the_same_bytes_under_windows_text_mode(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Text files end lines with CRLF there, and a redirected stdout is cp1252 with CRLF too."""
    text_files_as_on_windows(monkeypatch)
    reached = stdout_as_on_windows(monkeypatch)
    app(["fix", "--repo", str(tree), "--pack", PACK, "--apply", "--json"], standalone_mode=False)
    ran = folder(tree)
    assert reached.getvalue() == (ran / "plan.json").read_bytes()
    written = [path for path in ran.rglob("*") if path.is_file()]
    assert [path.name for path in written if b"\r" in path.read_bytes()] == []
    assert {"REPORT.md", "plan.json", "run.json"} <= {path.name for path in written}


def test_the_summary_names_every_file_on_the_plan_and_where_the_evidence_went(
    tree: Path,
) -> None:
    result = fix(tree)
    assert result.exit_code == 0
    assert "app.py  (1 hunk(s), configure-to-client" in result.output
    assert "Mode plan: a dry run. Nothing in the repository was written;" in result.output
    assert f"Evidence: {folder(tree)}" in result.output


def test_the_printed_diff_hides_the_value_of_a_secret_named_variable(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shape the redactor cannot recognise, in a comment on a removed line."""
    value = "correct-horse-battery-staple"
    source = (tree / "app.py").read_text(encoding="utf-8")
    (tree / "app.py").write_text(
        source.replace('"gemini-1.5-flash")', f'"gemini-1.5-flash")  # {value}'), encoding="utf-8"
    )
    monkeypatch.setenv("OBELIZE_TEST_TOKEN", value)
    result = fix(tree)
    assert result.exit_code == 0, result.output
    assert value not in result.stdout
    assert "# [REDACTED:OBELIZE_TEST_TOKEN]" in result.stdout
    assert value in (folder(tree) / "patch.diff").read_text(encoding="utf-8")


def test_a_repository_with_nothing_to_write_says_so_rather_than_printing_a_table(
    tmp_path: Path,
) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    result = runner.invoke(app, ["fix", "--repo", str(root), "--pack", PACK])
    assert result.exit_code == 0
    assert "0 finding(s)" in result.output


def test_a_run_folder_that_cannot_be_written_exits_one_and_says_so(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As `scan` does; it matters more here, because this run may have written files."""

    def refuse(*arguments: Any, **keywords: Any) -> Any:
        raise run_dir.EvidenceError("the disk said no")

    monkeypatch.setattr(run_dir, "write", refuse)
    result = fix(tree)
    assert result.exit_code == 1
    assert "the disk said no" in result.output


def test_a_run_that_cannot_be_planned_exits_one(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from obelize.transforms import codemod

    def refuse(*arguments: Any, **keywords: Any) -> Any:
        raise codemod.CodemodError("the pack contradicts itself")

    monkeypatch.setattr(codemod, "run", refuse)
    result = fix(tree)
    assert result.exit_code == 1
    assert "could not be planned" in result.output


def test_a_file_obelize_wrote_that_does_not_compile_fails_before_any_command(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rules compile their output before writing, so the gate is stubbed to test its wiring."""
    from obelize.verify import cheap

    monkeypatch.setattr(cheap, "uncompilable", lambda root, paths: ("app.py",))
    result = fix(tree, "--apply", "--verify", f"{PYTHON} -c pass")
    assert result.exit_code == 3
    record = json.loads((folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["status"] == "fail"
    assert record["verify"]["reason"] == "changed_file_does_not_compile"
    assert record["verify"]["commands"] == []
    assert record["verify"]["baseline"]["status"] == "pass"
    assert (
        "Verification: fail (changed_file_does_not_compile), 1 command(s) ran before the patch"
        in result.output.splitlines()
    )


def test_a_junit_report_reaches_the_run_folder_under_its_phase(tree: Path) -> None:
    """`verify.junit` fires only for pytest, so the report is placed by hand."""
    phase = tree.parent / "phase"
    phase.mkdir()
    assert commands.reports(phase) == {}
    (phase / "1.xml").write_bytes(b"<testsuite/>")
    assert commands.reports(phase) == {"1.xml": b"<testsuite/>"}


@pytest.fixture
def suite(tmp_path: Path) -> Path:
    """A one-test suite outside the repo, where a `.py` file would change the plan."""
    root = tmp_path / "suite"
    root.mkdir()
    (root / "test_one.py").write_text("def test_one():\n    assert True\n", encoding="utf-8")
    return root


def test_a_junit_report_the_runner_produced_lands_under_its_phase(tree: Path, suite: Path) -> None:
    """`verify.junit` recognises `python -m pytest` and adds `--junitxml` in both phases."""
    command = f"{PYTHON} -m pytest -q {quoted(suite)}"
    assert fix(tree, "--apply", "--verify", command).exit_code == 0
    record = json.loads((folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["commands"][0]["junit"] == "verify/after/1.junit.xml"
    assert record["verify"]["baseline"]["commands"][0]["junit"] == "verify/baseline/1.junit.xml"
    for relative in ("verify/after/1.junit.xml", "verify/baseline/1.junit.xml"):
        assert (folder(tree) / relative).read_bytes().startswith(b"<?xml")


def test_a_report_that_cannot_be_deleted_does_not_stop_the_run_being_recorded(
    tree: Path, suite: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reports' temporary folder is left behind, which is the control: its cleanup failed."""
    temporary = tmp_path / "temporary"
    reports_held_as_on_windows(monkeypatch, temporary)
    command = f"{PYTHON} -m pytest -q {quoted(suite)}"
    result = fix(tree, "--apply", "--verify", command)
    assert result.exit_code == 0, result.output
    record = json.loads((folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["status"] == "pass"
    assert (folder(tree) / "verify" / "after" / "1.junit.xml").exists()
    assert len(list(temporary.glob("*/*/1.junit.xml"))) == 2


def test_junit_is_not_asked_for_when_the_configuration_turns_it_off(
    tree: Path, suite: Path
) -> None:
    (tree / ".obelize.yml").write_text("verify:\n  junit: false\n", encoding="utf-8")
    command = f"{PYTHON} -m pytest -q {quoted(suite)}"
    result = fix(tree, "--apply", "--allow-dirty", "--verify", command)
    assert result.exit_code == 0
    record = json.loads((folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["commands"][0]["junit"] is None
    assert not (folder(tree) / "verify" / "after" / "1.xml").exists()


HINT = "came from the environment obelize runs in"


@SHEBANG
@pytest.mark.parametrize(
    ("inside", "code", "hinted"),
    [(True, 1, True), (False, 1, False), (True, 0, False)],
    ids=["obelizes_own_and_failing", "anothers_and_failing", "obelizes_own_and_passing"],
)
def test_a_baseline_run_from_obelizes_own_environment_says_so(
    tree: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inside: bool,
    code: int,
    hinted: bool,
) -> None:
    """Under `uv run` a bare `pytest` is obelize's; only a failing baseline from it is hinted."""
    own = tmp_path / "obelize-env"
    bin_dir = (own if inside else tmp_path / "project-env") / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "pytest").write_text(f"#!/bin/sh\nexit {code}\n", encoding="utf-8")
    (bin_dir / "pytest").chmod(0o755)
    monkeypatch.setattr(sys, "prefix", str(own))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    result = fix(tree, "--apply", "--verify", "pytest -q")
    assert result.exit_code == (6 if code else 0)
    record = json.loads((folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["baseline"]["commands"][0]["in_obelize_environment"] is inside
    hint = (
        "{0} failed, and its program " + HINT + ", which may not be your project's. "
        "To run your project's tests, name its interpreter: {1}."
    )
    tests = '--verify "/path/to/your/project/.venv/bin/python -m pytest -q"'
    # Every hint, so a command that started and failed is not also said to have never started.
    shown = [line for line in result.stdout.splitlines() if line.startswith("Hint:")]
    assert shown == ([f"Hint: {hint.format('pytest -q', tests)}"] if hinted else [])
    documented = f"**Hint:** {hint.format('`pytest -q`', f'`{tests}`')}"
    written = (folder(tree) / "REPORT.md").read_text(encoding="utf-8")
    assert written.count("**Hint:**") == int(hinted)
    assert (documented in written) is hinted


@SHEBANG
def test_a_baseline_that_timed_out_in_obelizes_own_environment_is_not_said_to_have_failed(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout is `inconclusive`, and the hint names it as that run ended."""
    own = tmp_path / "obelize-env"
    bin_dir = own / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "pytest").write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    (bin_dir / "pytest").chmod(0o755)
    monkeypatch.setattr(sys, "prefix", str(own))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    result = fix(tree, "--apply", "--timeout", "1", "--verify", "pytest -q")
    assert result.exit_code == 6, result.output
    record = json.loads((folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["baseline"]["commands"][0]["reason"] == "timeout"
    (hint,) = [line for line in result.stdout.splitlines() if line.startswith("Hint:")]
    assert hint.startswith(f"Hint: pytest -q timed out, and its program {HINT}, ")


def test_a_model_flag_that_is_not_valid_names_the_file_obelize_read(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`XDG_CONFIG_HOME` moves the user's file away from `~/.config`."""
    home = tmp_path / "elsewhere"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    result = fix(tree, "--model", "openai_compat")
    assert result.exit_code == 2, result.output
    assert result.stderr.splitlines()[0] == (
        f"--model openai_compat with the model block in {home / 'obelize' / 'config.yml'} "
        "is not valid:"
    )


def test_a_command_error_carries_the_code_it_leaves_by() -> None:
    error = CommandError("no", 4)
    assert str(error) == "no"
    assert error.code == 4


def test_the_prompt_asks_once_and_answers_what_it_was_told(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reached only on a terminal with no CI and no flag."""
    monkeypatch.setattr("typer.confirm", lambda *arguments, **keywords: True)
    assert cli._ask("pytest -q") is True
    assert "This repository asks to run: pytest -q" in capsys.readouterr().out


@pytest.mark.skipif(AS_ROOT, reason="root writes into a directory it may not")
def test_a_write_the_filesystem_refuses_after_the_baseline_ran(tmp_path: Path) -> None:
    """A read-only directory passes the preflight but fails the rename: nothing to verify."""
    root = tmp_path / "locked"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "app.py").write_text(LEGACY, encoding="utf-8")
    with deny(root / "pkg", writes_only=True):
        result = runner.invoke(
            app,
            [
                "fix",
                "--repo",
                str(root),
                "--pack",
                PACK,
                "--apply",
                "--verify",
                f"{PYTHON} -c pass",
            ],
        )
    assert result.exit_code == 5, result.output
    record = json.loads((folder(root) / "run.json").read_text(encoding="utf-8"))
    assert record["file_edits"] == []
    assert [one["code"] for one in record["refused"]] == ["unreadable"]
    assert record["verify"]["reason"] == "no_changes_to_verify"
    assert record["verify"]["baseline"]["status"] == "pass"
    assert "Not written: pkg/app.py: the file could not be read or written" in result.stdout
    assert result.stdout.splitlines()[-1] == (
        "Next: fix what the Not written line names and run again; no flag skips this check."
    )
    # The journal's copy is discarded with the failed write.
    assert not (folder(root) / "snapshots").exists()


@pytest.mark.skipif(AS_ROOT, reason="root writes into a directory it may not")
def test_a_refused_write_has_nothing_to_verify_whatever_the_ladder_would_have_said(
    tmp_path: Path,
) -> None:
    """`policy_refused` would send the reader to the trust ladder for a directory problem."""
    root = tmp_path / "locked"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "app.py").write_text(LEGACY, encoding="utf-8")
    (root / ".obelize.yml").write_text("verify:\n  commands:\n    - pytest -q\n", encoding="utf-8")
    with deny(root / "pkg", writes_only=True):
        result = runner.invoke(
            app, ["fix", "--repo", str(root), "--pack", PACK, "--apply", "--non-interactive"]
        )
    assert result.exit_code == 5, result.output
    record = json.loads((folder(root) / "run.json").read_text(encoding="utf-8"))
    assert record["verify"]["reason"] == "no_changes_to_verify"


def test_the_summary_says_which_planned_files_were_written_and_which_were_not(
    tree: Path,
) -> None:
    """A dry run has no such column: nothing was attempted, and `no` rows would read as failure."""
    planned = fix(tree).output
    assert not [line for line in planned.splitlines() if line.endswith("  written")]
    applied = fix(tree, "--apply", "--verify", f"{PYTHON} -c pass")
    assert applied.exit_code == 0
    assert "app.py  (1 hunk(s), configure-to-client, generative-model-calls, rename-import)" in (
        applied.output
    )
    for line in applied.output.splitlines():
        if line.startswith("  app.py") or line.startswith("  requirements.txt"):
            assert line.endswith("  written"), line


def test_a_run_with_nothing_to_write_never_asks_about_a_command(tree: Path) -> None:
    """The record is `no_changes_to_verify` either way; only the early return spares the prompt."""
    from obelize.commands import fix as fixer
    from obelize.models import Config, VerifyConfig
    from obelize.packs import loader
    from obelize.verify.runner import Mode

    assert fix(tree, "--apply", "--verify", f"{PYTHON} -c pass").exit_code == 0
    subprocess.run(["git", "-C", str(tree), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tree), "-c", "commit.gpgsign=false", "commit", "-qm", "after"],
        check=True,
    )
    asked: list[str] = []

    def spy(command: str) -> bool:
        asked.append(command)
        return True

    # Through the request, not the CLI: the prompt needs a terminal, which a test lacks.
    outcome = fixer.run(
        fixer.Request(
            root=tree,
            packs=(loader.load(PACK),),
            named=True,
            config=Config(verify=VerifyConfig(commands=("pytest -q",))),
            source="file",
            cli_commands=(),
            mode=Mode(tty=True),
            config_dir=tree.parent / "config",
            environ={},
            argv=("fix", "--apply"),
            apply=True,
            ask=spy,
        )
    )
    assert asked == []
    assert outcome.exit_code == 4
    assert outcome.record.verify is not None
    assert outcome.record.verify.reason == "no_changes_to_verify"


def test_an_apply_on_a_tree_git_cannot_describe_is_refused_as_unknown(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `git status` that gives no answer must not read as a clean tree."""
    real = gitutil.run

    def decline(root: Path, *arguments: str) -> str | None:
        return None if arguments[0] == "status" else real(root, *arguments)

    monkeypatch.setattr(gitutil, "run", decline)
    before = (tree / "app.py").read_bytes()

    result = fix(tree, "--apply")

    assert result.exit_code == 5, result.output
    assert (tree / "app.py").read_bytes() == before
    record = json.loads((folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert [row["code"] for row in record["refused"]] == ["tree_unknown"]
    assert record["git_dirty"] is None
    assert _refusal(result.output).endswith("run git status to see why, or pass --allow-dirty")
    assert result.stdout.splitlines()[-1] == (
        f"Next: run git -C {copied(tree)} status to see why git failed, "
        "or run again with --allow-dirty."
    )


def test_an_apply_on_a_dirty_tree_names_the_flag_that_permits_it(tree: Path) -> None:
    (tree / "requirements.txt").write_text("google-generativeai==0.8.5\n", encoding="utf-8")
    result = fix(tree, "--apply")
    assert result.exit_code == 5, result.output
    assert _refusal(result.output).endswith("commit or stash them, or pass --allow-dirty")


def test_an_apply_refused_only_over_an_untracked_file_says_to_commit_it(tree: Path) -> None:
    """`git stash` leaves an untracked file where it is, so it would not unblock this run."""
    subprocess.run(["git", "-C", str(tree), "rm", "-q", "--cached", "requirements.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(tree), "-c", "commit.gpgsign=false", "commit", "-qm", "untrack"],
        check=True,
    )
    (tree / "other.py").write_text(LEGACY, encoding="utf-8")
    result = fix(tree, "--apply")
    assert result.exit_code == 5, result.output
    assert _refusal(result.output) == (
        "Not written: git does not track 2 file(s) this run would edit, so git diff could not "
        "show the change; commit them (git add, then git commit), or pass --allow-dirty"
    )
    assert "stash" not in result.output
    assert result.stdout.splitlines()[-1] == (
        "Next: commit the file(s) git does not track (git add, then git commit), "
        "or run again with --allow-dirty."
    )


def test_a_tracked_file_the_baseline_changes_is_not_called_untracked(tree: Path) -> None:
    """The tree is clean when the run starts; the tests then change a tracked file."""
    touch = f"{PYTHON} -c \"open('requirements.txt', 'a').write('# touched')\""
    result = fix(tree, "--apply", "--verify", touch)
    assert result.exit_code == 5, result.output
    record = json.loads((folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert record["git_dirty"] is False
    assert _refusal(result.output).endswith("commit or stash them, or pass --allow-dirty")
    assert result.stdout.splitlines()[-1] == (
        "Next: commit or stash your changes, or run again with --allow-dirty."
    )


def test_tests_that_ran_before_a_refused_write_are_counted_and_kept(
    tree: Path, tmp_path: Path
) -> None:
    """The tests change a tracked file, so the write after them is refused."""
    suite = tmp_path / "touching"
    suite.mkdir()
    (suite / "test_touch.py").write_text(
        "def test_touch():\n    open('requirements.txt', 'a').write('# touched')\n",
        encoding="utf-8",
    )
    command = f"{PYTHON} -m pytest -q {quoted(suite)}"
    result = fix(tree, "--apply", "--verify", command)
    assert result.exit_code == 5, result.output
    (line,) = [one for one in result.output.splitlines() if one.startswith("Verification:")]
    assert line == (
        "Verification: not_run (no_changes_to_verify), 1 command(s) ran before the patch"
    )
    record = json.loads((folder(tree) / "run.json").read_text(encoding="utf-8"))
    (row,) = record["verify"]["baseline"]["commands"]
    assert (row["command"], row["status"]) == (command, "pass")
    spent = record["timings"]["verify_ms"]
    assert spent is not None, record["timings"]
    assert spent >= row["duration_ms"]
    assert (folder(tree) / row["junit"]).read_bytes().startswith(b"<?xml")
    index = folder(tree) / "verify" / "verify.json"
    assert json.loads(index.read_text(encoding="utf-8")) == record["verify"]
    assert "### Baseline" in (folder(tree) / "REPORT.md").read_text(encoding="utf-8")


def _refusal(output: str) -> str:
    """The one line saying why the working tree was not written."""
    (line,) = [one for one in output.splitlines() if one.startswith("Not written: ")]
    return line


def test_an_apply_interrupted_after_the_write_can_still_be_undone(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second verify call (the after-phase) is interrupted; the originals are already saved."""
    calls: list[int] = []
    run = verifier.run

    def interrupted(*arguments: Any, **keywords: Any) -> Any:
        calls.append(1)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return run(*arguments, **keywords)

    monkeypatch.setattr(verifier, "run", interrupted)
    original = (tree / "app.py").read_bytes()
    # 130, as an interrupted process exits at a terminal.
    result = runner.invoke(
        app,
        [
            "fix",
            "--repo",
            str(tree),
            "--pack",
            PACK,
            "--apply",
            "--verify",
            f"{PYTHON} -c pass",
        ],
    )
    assert calls == [1, 1], "the after-phase was reached"
    assert result.exit_code == 130, result.output
    assert (tree / "app.py").read_bytes() != original, "the write happened before the interrupt"
    (run_id,) = [path.name for path in (tree / ".obelize" / "runs").iterdir()]
    undone = runner.invoke(app, ["undo", "--repo", str(tree), "--run", run_id])
    assert undone.exit_code == 0, undone.output
    assert (tree / "app.py").read_bytes() == original


def test_a_run_folder_that_is_a_link_is_refused_before_anything_is_written(
    tree: Path, tmp_path: Path
) -> None:
    """The folder is made first, so a link there stops the run before any write."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link(tree / ".obelize", elsewhere)
    before = {name: (tree / name).read_bytes() for name in ("app.py", "requirements.txt")}
    result = fix(tree, "--apply")
    assert result.exit_code == 1, result.output
    assert {name: (tree / name).read_bytes() for name in before} == before
    assert list(elsewhere.iterdir()) == []


def test_a_journal_the_disk_refuses_stops_the_run_before_the_write(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*arguments: Any, **keywords: Any) -> Any:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(run_dir, "_artefact", refuse)
    before = {name: (tree / name).read_bytes() for name in ("app.py", "requirements.txt")}
    result = fix(tree, "--apply")
    assert result.exit_code == 1, result.output
    assert "No file in the repository was changed." in result.output
    assert {name: (tree / name).read_bytes() for name in before} == before


def test_a_journal_is_the_same_bytes_under_windows_text_mode(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It outlives an apply stopped before its record, which `obelize undo` then reads."""

    def refuse(*arguments: Any, **keywords: Any) -> Any:
        raise run_dir.EvidenceError("the run folder could not be written: no")

    text_files_as_on_windows(monkeypatch)
    monkeypatch.setattr(run_dir, "write", refuse)
    assert fix(tree, "--apply").exit_code == 1
    (journaled,) = (tree / ".obelize" / "runs").iterdir()
    assert b"\r" not in (journaled / "journal.json").read_bytes()


def test_an_apply_that_stops_before_its_record_leaves_git_nothing_to_add_either(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The journal's copies of the originals are down before any record is."""

    def refuse(*arguments: Any, **keywords: Any) -> Any:
        raise run_dir.EvidenceError("the run folder could not be written: no")

    monkeypatch.setattr(run_dir, "write", refuse)
    assert fix(tree, "--apply").exit_code == 1
    (journaled,) = (tree / ".obelize" / "runs").iterdir()
    assert (journaled / "journal.json").is_file()
    listed = ["git", "-C", str(tree), "status", "--porcelain", "--untracked-files=all"]
    status = subprocess.run([*listed, "--", ".obelize"], check=True, capture_output=True, text=True)
    assert status.stdout == ""


def test_a_journal_the_disk_fills_halfway_leaves_git_nothing_to_add(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ignore file goes down before the first copy of an original."""
    copy = run_dir._artefact

    def fill(folder: Path, relative: str, data: bytes) -> None:
        copy(folder, relative, data)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(run_dir, "_artefact", fill)
    assert fix(tree, "--apply").exit_code == 1
    (journaled,) = (tree / ".obelize" / "runs").iterdir()
    assert any(path.is_file() for path in journaled.rglob("*")), "an original was copied"
    listed = ["git", "-C", str(tree), "status", "--porcelain", "--untracked-files=all"]
    status = subprocess.run([*listed, "--", ".obelize"], check=True, capture_output=True, text=True)
    assert status.stdout == ""


def test_an_id_that_climbs_out_of_the_runs_is_not_read_as_a_journal(tree: Path) -> None:
    """Asked of the reader: the CLI refuses the id first, and `RunFolder` would follow `..`."""
    (tree / ".obelize" / "runs").mkdir(parents=True)
    outside = tree / ".obelize" / "evil"
    outside.mkdir()
    (outside / "journal.json").write_text(
        json.dumps({"run_id": "20260917T142530Z-3f9a1c72", "file_edits": []}), encoding="utf-8"
    )
    assert run_dir.interrupted(tree, "../evil") is None
    assert run_dir.interrupted(tree, "20260917T142530Z-3f9a1c72") is None


def test_a_plan_keeps_no_copy_of_what_it_did_not_write(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*arguments: Any, **keywords: Any) -> Any:
        raise run_dir.EvidenceError("a dry run asked for a journal")

    monkeypatch.setattr(run_dir, "journal", refuse)
    assert fix(tree).exit_code == 0


def _commit(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", "commit", "-qm", "more"],
        check=True,
    )


@pytest.mark.parametrize("extra", [(), ("--apply",)], ids=["dry_run", "apply"])
def test_a_blocked_run_says_why_nothing_is_planned_and_how_to_unblock_it(
    tree: Path, extra: tuple[str, ...]
) -> None:
    """Otherwise it counts rows `auto` and writes none of them, and gives no reason."""
    (tree / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.9"\n', encoding="utf-8"
    )
    _commit(tree)
    lines = fix(tree, *extra).output.splitlines()
    assert lines[4].startswith("pyproject.toml declares Python >=3.9, which allows")
    assert lines[4].endswith(
        "To migrate, raise the minimum in pyproject.toml to >=3.10 and run again."
    )
    assert lines[5:7] == ["", "No change planned."]
    assert "runtime_unsupported (5 of 5)" in lines[7]
    assert any("5 finding(s): 5 needs review" in line for line in lines)


def test_a_declared_floor_the_new_distribution_supports_blocks_nothing(tree: Path) -> None:
    (tree / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.10"\n', encoding="utf-8"
    )
    _commit(tree)
    output = fix(tree).output
    assert "declares Python" not in output
    assert "No change planned." not in output
    assert "  app.py  (1 hunk(s)" in output


@pytest.mark.parametrize("empty", [True, False], ids=["empty", "planned"])
def test_a_dry_run_calls_the_patch_a_change_only_when_there_is_one(tree: Path, empty: bool) -> None:
    if empty:
        (tree / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        (tree / "requirements.txt").write_text("requests\n", encoding="utf-8")
    result = fix(tree)
    assert result.exit_code == 0, result.output
    dry = ": a dry run. Nothing in the repository was written"
    change = "" if empty else "; {0} holds the change it would make"
    assert f"Mode plan{dry}{change.format('patch.diff')}." in result.stdout.splitlines()
    documented = (folder(tree) / "REPORT.md").read_text(encoding="utf-8").splitlines()
    assert f"- **Mode** `plan`{dry}{change.format('`patch.diff`')}." in documented
    assert ("No change planned." in result.output.splitlines()) is empty


@pytest.mark.parametrize(
    ("command", "ran"),
    [
        (f"{PYTHON} -c pass", "1 command(s) ran"),
        (f'{PYTHON} -c "raise SystemExit(1)"', "1 command(s) ran before the patch"),
        ("/nonexistent/obelize-no-such-program", "0 command(s) ran before the patch"),
    ],
    ids=["both_phases", "baseline_failed", "not_executable"],
)
def test_the_summary_counts_the_commands_that_really_ran(
    tree: Path, command: str, ran: str
) -> None:
    """A failing baseline skips the after-phase, and its commands still ran."""
    result = fix(tree, "--apply", "--verify", command)
    (line,) = [one for one in result.output.splitlines() if one.startswith("Verification:")]
    assert line.endswith(f", {ran}"), line


TESTS = f"--verify {copied('<project python> -m pytest -q')}"


def test_a_run_in_the_current_directory_names_no_repository_in_its_next_step(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tree)
    result = runner.invoke(app, ["fix", "--apply", "--verify", f"{PYTHON} -c pass"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-2:] == [
        f"Evidence: {Path('.obelize', 'runs', folder(tree).name)}",
        f"Next: git diff shows the change; obelize undo --run {folder(tree).name} puts it back.",
    ]


@posix_only("a POSIX shell reads single quotes; the test below reads Windows' form through cmd")
def test_a_next_step_spells_the_repository_as_a_shell_reads_it(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spaced = tree.rename(tree.parent / "my repo")
    monkeypatch.chdir(spaced.parent)
    result = runner.invoke(
        app, ["fix", "--repo", "my repo", "--apply", "--verify", f"{PYTHON} -c pass"]
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1] == (
        f"Next: git -C 'my repo' diff shows the change; "
        f"obelize undo --run {folder(spaced).name} --repo 'my repo' puts it back."
    )


WINDOWS_TESTS = '--verify "<project python> -m pytest -q"'


@pytest.mark.parametrize(
    ("git", "source", "verify", "expected"),
    [
        (
            True,
            LEGACY,
            f"{PYTHON} -c pass",
            'git -C "my repo" diff shows the change; obelize undo --run {run} --repo "my repo" '
            "puts it back.",
        ),
        (
            False,
            LEGACY,
            f"{PYTHON} -c pass",
            '{folder}\\patch.diff holds the change; obelize undo --run {run} --repo "my repo" '
            "puts it back.",
        ),
        (
            False,
            ESCAPING,
            None,
            "{withheld} finding(s) are left for you to review, listed in {folder}\\REPORT.md.",
        ),
        (
            True,
            LEGACY,
            "/nonexistent/obelize-no-such-program -q",
            'obelize undo --run {run} --repo "my repo", then obelize fix --apply --repo "my repo" '
            f"{WINDOWS_TESTS}, with tests that pass before the change.",
        ),
        (
            True,
            LEGACY,
            None,
            f'obelize verify --run {{run}} --repo "my repo" {WINDOWS_TESTS} checks the change '
            "with your tests.",
        ),
    ],
    ids=["git_diff", "patch", "review", "never_started", "verify"],
)
def test_a_next_step_is_spelled_for_windows_shells_where_they_read_it(
    tree: Path,
    monkeypatch: pytest.MonkeyPatch,
    git: bool,
    source: str,
    verify: str | None,
    expected: str,
) -> None:
    """Windows' quoting and path class, stubbed here: cmd.exe reads no single quote, and the
    run folder comes spelled with backslashes."""
    monkeypatch.setattr(shell, "quote", windows_programs.quote)
    monkeypatch.setattr(report, "PurePath", PureWindowsPath)
    spaced = tree.parent / "my repo"
    if git:
        tree.rename(spaced)
    else:
        spaced.mkdir()
        (spaced / "app.py").write_text(source, encoding="utf-8")
    monkeypatch.chdir(spaced.parent)
    extra = [] if verify is None else ["--verify", verify]
    lines = runner.invoke(app, ["fix", "--repo", "my repo", "--apply", *extra]).stdout.splitlines()
    record = json.loads((folder(spaced) / "run.json").read_text(encoding="utf-8"))
    run = folder(spaced).name
    assert lines[-1] == "Next: " + expected.format(
        run=run, folder=f"my repo\\.obelize\\runs\\{run}", withheld=len(record["withheld"])
    )
    hinted = [line for line in lines if line.endswith(f"name its interpreter: {WINDOWS_TESTS}.")]
    assert len(hinted) == int(verify is not None and verify.startswith("/nonexistent/"))


@windows_only("POSIX shells read single quotes; the stubbed test above prints Windows' form")
def test_a_next_step_hands_the_repository_to_a_program_whole_through_cmd(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: cmd.exe hands the single-quoted spelling on as two arguments."""
    spaced = tree.rename(tree.parent / "my repo")
    monkeypatch.chdir(spaced.parent)
    result = runner.invoke(
        app, ["fix", "--repo", "my repo", "--apply", "--verify", f"{PYTHON} -c pass"]
    )
    assert result.exit_code == 0, result.output
    line = result.stdout.splitlines()[-1]
    spelled = line.split(" --repo ", 1)[1].removesuffix(" puts it back.")

    def through_cmd(argument: str) -> list[str]:
        echo = f'{copied(sys.executable)} -c "import json, sys; print(json.dumps(sys.argv[1:]))"'
        # How cmd.exe reads the line is what is tested.
        shown = subprocess.run(  # noqa: S602
            f"{echo} {argument}",
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
        read: list[str] = json.loads(shown)
        return read

    assert through_cmd(shlex.quote("my repo")) == ["'my", "repo'"]
    assert through_cmd(spelled) == ["my repo"]
    assert line.startswith(f"Next: git -C {spelled} diff shows the change; ")


def test_outside_git_the_next_step_names_the_patch_instead_of_git_diff(tmp_path: Path) -> None:
    """With no repository `git diff` fails, and `patch.diff` holds what an exit `0` wrote."""
    root = tmp_path / "plain"
    root.mkdir()
    (root / "app.py").write_text(LEGACY, encoding="utf-8")
    (root / "requirements.txt").write_text("google-generativeai==0.8.6\n", encoding="utf-8")
    result = fix(root, "--apply", "--verify", f"{PYTHON} -c pass")
    assert result.exit_code == 0, result.output
    patch = folder(root) / "patch.diff"
    assert result.stdout.splitlines()[-1] == (
        f"Next: {patch} holds the change; obelize undo --run {folder(root).name} "
        f"--repo {copied(root)} puts it back."
    )
    assert "+++ b/app.py" in patch.read_text(encoding="utf-8")


@windows_only("POSIX has one separator; test_report.py gives the report Windows' path class")
def test_a_path_printed_under_the_repository_takes_one_separator(tmp_path: Path) -> None:
    """Control: the run folder joined with `/` would hold both separators."""
    root = tmp_path / "plain"
    root.mkdir()
    (root / "app.py").write_text(LEGACY, encoding="utf-8")
    result = fix(root, "--apply", "--verify", f"{PYTHON} -c pass")
    assert result.exit_code == 0, result.output
    evidence = str(folder(root))
    assert {"/", "\\"} <= set(f"{evidence}/patch.diff")
    shown = result.stdout.splitlines()[-1].removeprefix("Next: ").split(" holds the change")[0]
    assert shown == f"{evidence}\\patch.diff"


def test_a_command_that_never_started_is_named_with_the_interpreter_to_try(tree: Path) -> None:
    program = "/nonexistent/obelize-no-such-program"
    result = fix(tree, "--apply", "--verify", f"{program} -q")
    assert result.exit_code == 6, result.output
    # It never started, so the baseline did not pass and `obelize verify` would run nothing.
    assert result.stdout.splitlines()[-1] == (
        f"Next: obelize undo --run {folder(tree).name} --repo {copied(tree)}, then obelize fix "
        f"--apply --repo {copied(tree)} {TESTS}, with tests that pass before the change."
    )
    hint = (
        "{0} did not start: there is no such program, or no permission to run it. "
        "To run your project's tests, name its interpreter: {1}."
    )
    assert f"Hint: {hint.format(program, TESTS)}" in result.stdout.splitlines()
    documented = f"**Hint:** {hint.format(f'`{program}`', f'`{TESTS}`')}"
    assert documented in (folder(tree) / "REPORT.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("extra", [(), ("--apply",)], ids=["dry_run", "apply"])
def test_a_run_with_nothing_to_write_names_what_held_back_the_most(
    tmp_path: Path, extra: tuple[str, ...]
) -> None:
    root = tmp_path / "held"
    root.mkdir()
    (root / "app.py").write_text(ESCAPING, encoding="utf-8")
    (root / "adapter.py").write_text(MOCKED, encoding="utf-8")
    result = runner.invoke(app, ["fix", "--repo", str(root), "--pack", PACK, *extra])
    lines = result.stdout.splitlines()
    start = lines.index("No change planned.")
    assert lines[start + 1 : start + 3] == [
        "Most common reason a finding was left for review: model_object_escapes (3 of 4).",
        "",
    ]


def test_a_run_with_a_plan_names_no_reason_for_holding_back(tree: Path) -> None:
    (tree / "adapter.py").write_text(MOCKED, encoding="utf-8")
    result = fix(tree)
    assert result.exit_code == 0, result.output
    record = json.loads((folder(tree) / "run.json").read_text(encoding="utf-8"))
    assert record["withheld"], "something is held back"
    lines = result.stdout.splitlines()
    assert "No change planned." not in lines
    assert not [line for line in lines if line.startswith("Most common reason")]
