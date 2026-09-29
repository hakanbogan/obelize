"""What the verify oracle cannot pose: signal escalation, held pipes, the user's two files."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

import pytest

from obelize.config import ConfigError
from obelize.native import processes, windows_programs
from obelize.verify import runner
from platforms import MODE_BITS, PYTHON, SIGNALS, deny, program, quoted, windows_only

TOOLS = Path(__file__).resolve().parents[1] / "fixtures" / "verify" / "tools"


def written(config_dir: Path, text: str) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / runner.ALLOWLIST_FILENAME).write_text(text, encoding="utf-8")


def test_the_configuration_home_is_the_xdg_one_when_it_is_set() -> None:
    assert runner.config_home({"XDG_CONFIG_HOME": "/x", "HOME": "/h"}) == Path("/x/obelize")


def test_and_the_conventional_one_when_it_is_not() -> None:
    assert runner.config_home({"HOME": "/h"}) == Path("/h/.config/obelize")
    assert runner.config_home({"XDG_CONFIG_HOME": "", "HOME": "/h"}) == Path("/h/.config/obelize")


def test_an_environment_with_no_home_at_all_still_answers() -> None:
    """A daemon's environment: it must not raise in the middle of a trust check."""
    assert runner.config_home({}).name == "obelize"


def test_no_allowlist_is_an_empty_allowlist(tmp_path: Path) -> None:
    assert runner.allowlist(tmp_path / "nothing") == frozenset()


def test_an_empty_allowlist_file_is_too(tmp_path: Path) -> None:
    written(tmp_path, "")
    assert runner.allowlist(tmp_path) == frozenset()


def test_a_command_matches_on_what_would_be_executed(tmp_path: Path) -> None:
    """`pytest -q` and `pytest  -q` run the same argv, so the allowlist holds the split form."""
    written(tmp_path, 'verify:\n  allow:\n    - "pytest -q"\n')
    assert runner.allowlist(tmp_path) == frozenset({("pytest", "-q")})
    assert ("pytest", "-q") in runner.allowlist(tmp_path)


BROKEN = [
    ("verify:\n  allow: [1]\n", "is not valid"),
    ("verify:\n  allowed: []\n", "is not valid"),
    ("- a list\n", "is not valid"),
    ('verify:\n  allow: ["pytest |"]\n', "is not valid"),
    ("verify:\n  allow: []\n  allow: []\n", "duplicate key"),
    ("verify: [\n", "not valid YAML"),
]


@pytest.mark.parametrize(("text", "message"), BROKEN, ids=[m for _, m in BROKEN])
def test_an_allowlist_that_cannot_be_used_is_an_error(
    tmp_path: Path, text: str, message: str
) -> None:
    """Not an empty allowlist: that would silently run fewer of the user's own commands."""
    written(tmp_path, text)
    with pytest.raises(ConfigError, match=message):
        runner.allowlist(tmp_path)


def test_a_refusal_names_the_key_in_the_users_file_without_pydantics_prefix(
    tmp_path: Path,
) -> None:
    written(tmp_path, "model:\n  provider: openai_compat\n")
    with pytest.raises(ConfigError) as refused:
        runner.user_config(tmp_path)
    assert str(refused.value) == (
        f"{tmp_path / runner.ALLOWLIST_FILENAME} is not valid:\n"
        "  - model: provider 'openai_compat' needs base_url and model to be set"
    )


def test_a_misspelt_key_in_the_users_file_is_matched_against_that_files_keys(
    tmp_path: Path,
) -> None:
    """`verify.commands` belongs to `.obelize.yml`, so it is no suggestion for this file."""
    written(tmp_path, "verify:\n  alow: [pytest]\n  comands: [pytest]\n")
    with pytest.raises(ConfigError) as refused:
        runner.user_config(tmp_path)
    assert str(refused.value).splitlines()[1:] == [
        "  - unknown key 'verify.alow'; did you mean 'allow'?",
        "  - unknown key 'verify.comands'",
    ]


def test_an_unreadable_allowlist_is_an_error_too(tmp_path: Path) -> None:
    written(tmp_path, "verify:\n  allow: []\n")
    with (
        deny(tmp_path / runner.ALLOWLIST_FILENAME),
        pytest.raises(ConfigError, match="cannot be read"),
    ):
        runner.allowlist(tmp_path)


def test_no_store_is_no_approvals(tmp_path: Path) -> None:
    assert runner.approvals(tmp_path) == frozenset()


MALFORMED = ["not json at all", '["a list"]', '{"approvals": 3}', '{"approvals": [3, null]}']


@pytest.mark.parametrize("text", MALFORMED)
def test_a_store_that_does_not_parse_fails_closed(tmp_path: Path, text: str) -> None:
    """Unlike the allowlist: losing a cache of given answers costs one prompt, not the run."""
    (tmp_path / runner.APPROVALS_FILENAME).write_text(text, encoding="utf-8")
    assert runner.approvals(tmp_path) == frozenset()


def test_an_approval_is_keyed_by_the_repository_and_the_command_text(tmp_path: Path) -> None:
    runner.remember(tmp_path, "/repo/one", "pytest -q")
    assert runner.approvals(tmp_path) == frozenset({("/repo/one", runner.digest("pytest -q"))})
    assert ("/repo/two", runner.digest("pytest -q")) not in runner.approvals(tmp_path)
    assert ("/repo/one", runner.digest("pytest -q -x")) not in runner.approvals(tmp_path)


def test_an_approval_is_keyed_by_the_text_and_not_by_what_it_splits_into(
    tmp_path: Path,
) -> None:
    """An approval records the text somebody was shown, so a whitespace edit is asked again."""
    runner.remember(tmp_path, "/repo", "pytest -q")
    assert ("/repo", runner.digest("pytest  -q")) not in runner.approvals(tmp_path)
    assert runner.digest("pytest -q") != runner.digest("pytest  -q")


def test_remembering_one_command_does_not_forget_another(tmp_path: Path) -> None:
    runner.remember(tmp_path, "/repo", "pytest -q")
    runner.remember(tmp_path, "/repo", "mypy src")
    runner.remember(tmp_path, "/repo", "pytest -q")
    stored = json.loads((tmp_path / runner.APPROVALS_FILENAME).read_text(encoding="utf-8"))
    assert len(stored["approvals"]) == 2
    assert runner.approvals(tmp_path) == {
        ("/repo", runner.digest("pytest -q")),
        ("/repo", runner.digest("mypy src")),
    }


@MODE_BITS
def test_the_store_is_the_user_s_alone(tmp_path: Path) -> None:
    """An approval store another account can append to is an allowlist they keep."""
    home = tmp_path / "config"
    runner.remember(home, "/repo", "pytest -q")
    assert stat.S_IMODE((home / runner.APPROVALS_FILENAME).stat().st_mode) == 0o600
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_the_store_records_the_command_it_showed_somebody(tmp_path: Path) -> None:
    """The hash is the key; the text answers "what did I approve here"."""
    runner.remember(tmp_path, "/repo", "pytest -q")
    stored = json.loads((tmp_path / runner.APPROVALS_FILENAME).read_text(encoding="utf-8"))
    assert stored["approvals"][0]["command"] == "pytest -q"


def test_ci_is_presence_and_not_truth() -> None:
    """Any value, even empty or "false", means CI: failing closed costs nothing."""
    assert runner.Mode.of({"CI": ""}).ci is True
    assert runner.Mode.of({"CI": "false"}).ci is True
    assert runner.Mode.of({}).ci is False


def test_interactive_needs_all_three_conditions() -> None:
    assert runner.Mode.of({}, tty=True).interactive is True
    assert runner.Mode.of({"CI": "1"}, tty=True).interactive is False
    assert runner.Mode.of({}, tty=True, non_interactive=True).interactive is False
    assert runner.Mode.of({}, tty=False).interactive is False


def test_a_prompt_nobody_supplied_is_a_refusal(tmp_path: Path) -> None:
    """Reading "nobody answered" as yes would be the blanket trust flag ADR-007 refuses."""
    plan = runner.resolve(
        tmp_path,
        mode=runner.Mode(tty=True),
        config_dir=tmp_path / "config",
        repo_commands=["pytest -q"],
        ask=None,
    )
    assert plan == runner.Refused("pytest -q")


PYTEST_SHAPES = [
    ("pytest -q", True),
    ("py.test", True),
    ("/usr/bin/pytest -q", True),
    ("python -m pytest", True),
    ("python3.12 -m pytest tests", True),
    ("python -m mypy src", False),
    ("mypy src", False),
    ("python", False),
]


@pytest.mark.parametrize(("text", "recognised"), PYTEST_SHAPES, ids=[t for t, _ in PYTEST_SHAPES])
def test_only_a_pytest_command_is_asked_for_a_junit_report(
    tmp_path: Path, text: str, recognised: bool
) -> None:
    argv, junit = runner._argv(runner.Command.of(text, "cli"), tmp_path, 1)
    assert (junit is not None) is recognised
    assert (argv[-1].startswith("--junitxml=")) is recognised


WINDOWS_PYTEST_SHAPES = [
    ("'C:\\x\\pytest.exe' -q", True),
    ("C:/x/PYTEST.EXE -q", True),
    ("pytest.exe", True),
    ("python.exe -m pytest", True),
    ("'C:\\x\\python3.12.exe' -m pytest tests", True),
    ("mypy.exe src", False),
]


@pytest.mark.parametrize(
    ("text", "recognised"),
    WINDOWS_PYTEST_SHAPES,
    ids=["quoted-path", "upper-case", "exe", "python-exe", "versioned-python", "mypy"],
)
def test_a_pytest_named_as_windows_names_it_is_asked_for_a_junit_report_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, recognised: bool
) -> None:
    """Windows' reading of a program's name, stubbed here: POSIX keeps an extension."""
    monkeypatch.setattr(processes, "program_name", windows_programs.name)
    argv, junit = runner._argv(runner.Command.of(text, "cli"), tmp_path, 1)
    assert (junit is not None) is recognised
    assert (argv[-1].startswith("--junitxml=")) is recognised


@pytest.mark.parametrize("flag", ["--junitxml=mine.xml", "--junitxml"])
def test_a_command_that_already_asks_for_one_is_left_alone(tmp_path: Path, flag: str) -> None:
    """Adding a second would overrule the path the user chose."""
    argv, junit = runner._argv(runner.Command.of(f"pytest {flag} x", "cli"), tmp_path, 1)
    assert junit is None
    assert argv == ("pytest", flag, "x")


def test_no_destination_means_no_argument(tmp_path: Path) -> None:
    argv, junit = runner._argv(runner.Command.of("pytest -q", "cli"), None, 1)
    assert (argv, junit) == (("pytest", "-q"), None)


def test_a_junit_file_is_recorded_only_when_the_command_wrote_one(tmp_path: Path) -> None:
    """A pytest that could not start writes no report; the added flag is no evidence of one."""
    reports = tmp_path / "verify"
    reports.mkdir()
    assert runner._produced(reports, "1.junit.xml") is None
    (reports / "1.junit.xml").write_text("<x/>", encoding="utf-8")
    assert runner._produced(reports, "1.junit.xml") == "1.junit.xml"
    assert runner._produced(None, "1.junit.xml") is None
    assert runner._produced(reports, None) is None


def test_a_pytest_run_writes_its_report_where_it_was_told_to(tmp_path: Path) -> None:
    reports = tmp_path / "verify"
    reports.mkdir()
    (tmp_path / "test_one.py").write_text("def test_one():\n    assert True\n", encoding="utf-8")
    result = runner.execute(
        tmp_path,
        runner.Command.of(f"{PYTHON} -m pytest -q -p no:cacheprovider --no-cov", "cli"),
        timeout_s=120,
        environ=dict(os.environ),
        junit_dir=reports,
    )
    assert result.status == "pass", result.output
    assert result.junit == "1.junit.xml"
    assert (reports / "1.junit.xml").exists()


def test_a_command_reads_nothing_of_what_was_typed_to_obelize(tmp_path: Path) -> None:
    """pytest gives every test an empty stdin, so the oracle cannot tell closed from inherited."""
    typed, typing = os.pipe()
    os.write(typing, b"yes\n")
    os.close(typing)
    own = os.dup(0)
    os.dup2(typed, 0)
    try:
        result = runner.execute(
            tmp_path,
            runner.Command.of(f"{PYTHON} {quoted(TOOLS / 'environ.py')}", "cli"),
            timeout_s=30,
            environ=dict(os.environ),
        )
    finally:
        os.dup2(own, 0)
        os.close(own)
        os.close(typed)
    assert "STDIN=''" in result.output.splitlines()


@SIGNALS
def test_a_process_that_ignores_the_first_signal_gets_the_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a second signal ends a process holding the pipe on purpose; `GRACE_S` is shortened."""
    monkeypatch.setattr(runner, "GRACE_S", 0.3)
    started = time.monotonic()
    result = runner.execute(
        tmp_path,
        runner.Command.of(f"{PYTHON} {quoted(TOOLS / 'stubborn.py')} 60", "cli"),
        timeout_s=1,
        environ=dict(os.environ),
    )
    assert (result.status, result.reason) == ("inconclusive", "timeout")
    assert result.exit_code == -9, "SIGTERM was ignored, so SIGKILL is what ended it"
    assert time.monotonic() - started < 30, "the second signal did not arrive"


@SIGNALS
def test_the_second_signal_reaches_the_whole_group_and_not_only_its_leader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child ignores SIGTERM as its leader does, so only a SIGKILL to the group ends it."""
    monkeypatch.setattr(runner, "GRACE_S", 0.3)
    monkeypatch.setattr(runner, "DRAIN_S", 0.3)
    marker = tmp_path / "survived"
    result = runner.execute(
        tmp_path,
        runner.Command.of(f"{PYTHON} {quoted(TOOLS / 'stubborn.py')} 3 {quoted(marker)}", "cli"),
        timeout_s=1,
        environ=dict(os.environ),
    )
    assert (result.status, result.reason) == ("inconclusive", "timeout")
    time.sleep(3.5)
    assert not marker.exists(), "the child outlived the second signal"


@SIGNALS
def test_a_pipe_nobody_can_close_still_ends_the_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child in its own session escapes the group kill and holds the pipe, so EOF never comes."""
    monkeypatch.setattr(runner, "DRAIN_S", 0.3)
    started = time.monotonic()
    result = runner.execute(
        tmp_path,
        runner.Command.of(f"{PYTHON} {quoted(TOOLS / 'escapee.py')} 60", "cli"),
        timeout_s=1,
        environ=dict(os.environ),
    )
    escapee = int(result.output.split()[1])
    try:
        assert (result.status, result.reason) == ("inconclusive", "timeout")
        assert time.monotonic() - started < 30, "the read did not stop on its own"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(escapee, signal.SIGTERM)


def test_output_that_never_reaches_its_end_still_ends_the_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read is stubbed silent, since only a POSIX session holds the pipe past a kill."""
    monkeypatch.setattr(runner, "DRAIN_S", 0.3)
    started = time.monotonic()

    def silent(_stream: object, _size: int, timeout: float) -> None:
        assert time.monotonic() - started < 30, "the read did not stop on its own"
        time.sleep(timeout)

    monkeypatch.setattr(processes, "read", silent)
    result = runner.execute(
        tmp_path,
        runner.Command.of(f"{PYTHON} {quoted(TOOLS / 'slow.py')} 60", "cli"),
        timeout_s=1,
        environ=dict(os.environ),
    )
    assert (result.status, result.reason) == ("inconclusive", "timeout")


def test_killing_a_process_that_is_already_gone_is_not_an_error(tmp_path: Path) -> None:
    """The race between the deadline and the process ending on its own."""
    process = processes.spawn([sys.executable, "-c", "pass"], tmp_path, dict(os.environ))
    try:
        process.wait()
        runner._kill(process)
    finally:
        processes.close(process)
        with process:
            pass


@pytest.mark.parametrize(
    "failure", [KeyboardInterrupt, OSError], ids=["an interrupt", "a read that failed"]
)
def test_a_command_is_released_once_however_its_run_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    """On Windows releasing it ends its job, and an interrupt is when that matters most."""
    released: list[subprocess.Popen[bytes]] = []
    close = processes.close

    def spy(process: subprocess.Popen[bytes]) -> None:
        released.append(process)
        close(process)

    monkeypatch.setattr(processes, "close", spy)
    command = runner.Command.of(f"{PYTHON} -c pass", "cli")
    result = runner.execute(tmp_path, command, timeout_s=30, environ=dict(os.environ))
    assert result.status == "pass"
    assert len(released) == 1

    def failed(*_arguments: object) -> bytes:
        raise failure

    monkeypatch.setattr(processes, "read", failed)
    with pytest.raises(failure):
        runner.execute(tmp_path, command, timeout_s=30, environ=dict(os.environ))
    assert len(released) == 2
    with released[1]:
        pass


def test_the_suite_reads_no_real_user_configuration(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """`tests/conftest.py` isolates it: a real config names a model tests would send code to."""
    home = runner.config_home(os.environ)
    assert home.is_relative_to(tmp_path_factory.getbasetemp())
    assert not (home / runner.ALLOWLIST_FILENAME).exists()


@pytest.mark.parametrize(
    ("code", "verdict"),
    [(0, ("pass", None, 0)), (1, ("fail", "command_failed", 1))],
    ids=["a suite that passed", "a suite that failed"],
)
def test_a_command_that_ended_is_graded_by_its_own_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: int,
    verdict: tuple[str, str | None, int],
) -> None:
    """The child it leaves outlives the deadline; it is ended and does not decide the verdict."""
    monkeypatch.setattr(runner, "DRAIN_S", 0.3)
    marker = tmp_path / "survived"
    started = time.monotonic()
    result = runner.execute(
        tmp_path,
        runner.Command.of(
            f"{PYTHON} {quoted(TOOLS / 'leaves_a_child.py')} {code} 3 {quoted(marker)}", "cli"
        ),
        timeout_s=1,
        environ=dict(os.environ),
    )
    assert (result.status, result.reason, result.exit_code) == verdict
    assert time.monotonic() - started < 1, "the read waited for the child"
    time.sleep(3.5)
    assert not marker.exists(), "the child the command left behind was not ended"


@SIGNALS
def test_a_command_stopped_at_its_deadline_is_a_timeout_whatever_its_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "DRAIN_S", 0.3)
    result = runner.execute(
        tmp_path,
        runner.Command.of(f"{PYTHON} {quoted(TOOLS / 'obeys_term.py')} 60", "cli"),
        timeout_s=1,
        environ=dict(os.environ),
    )
    assert (result.status, result.reason, result.exit_code) == ("inconclusive", "timeout", 0)


def test_a_command_that_ended_just_before_its_deadline_is_still_not_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read after the end is cut at the deadline, and the verdict stays its own."""
    monkeypatch.setattr(runner, "DRAIN_S", 5.0)
    marker = tmp_path / "survived"
    result = runner.execute(
        tmp_path,
        runner.Command.of(
            f"{PYTHON} {quoted(TOOLS / 'leaves_a_child.py')} 0 3 {quoted(marker)}", "cli"
        ),
        timeout_s=1,
        environ=dict(os.environ),
    )
    assert (result.status, result.reason, result.exit_code) == ("pass", None, 0)


def test_a_program_is_looked_up_on_the_commands_own_path_and_only_when_bare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command's `PATH` is asked, not obelize's; a program named by path chose its own."""
    own = tmp_path / "obelize-env" / "bin"
    own.mkdir(parents=True)
    tool = program(own / "tool", passes=True)
    monkeypatch.setattr(sys, "prefix", str(own.parent))
    environ = {**os.environ, "PATH": f"{own}{os.pathsep}{os.defpath}"}
    for text, found in (("tool", True), (quoted(tool), False)):
        result = runner.execute(
            tmp_path, runner.Command.of(text, "cli"), timeout_s=5, environ=environ
        )
        assert (result.status, result.in_obelize_environment) == ("pass", found)


def test_the_environment_hint_asks_the_lookup_of_this_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows looks a program up differently from `shutil.which`, so its answer is stubbed."""
    asked: list[str] = []

    def inside(wanted: str, env: Mapping[str, str]) -> str:
        asked.append(wanted)
        return str(Path(sys.prefix, "bin", "python"))

    monkeypatch.setattr(processes, "locate", inside)
    result = runner.execute(
        tmp_path,
        runner.Command.of(f"{PYTHON} -c pass", "cli"),
        timeout_s=30,
        environ=dict(os.environ),
    )
    assert (result.status, result.in_obelize_environment) == ("pass", True)
    assert asked == [sys.executable]


@windows_only("POSIX runs the program the command's PATH names; the lookup test above shows it")
def test_a_program_planted_where_obelize_or_the_command_runs_is_not_the_one_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: `CreateProcess` looks in the current directory before `PATH`."""
    listed = tmp_path / "listed"
    planted = tmp_path / "planted"
    root = tmp_path / "root"
    for directory in (listed, planted, root):
        directory.mkdir()
    program(listed / "tool", passes=True)
    program(planted / "tool", passes=False)
    program(root / "tool", passes=False)
    monkeypatch.chdir(planted)
    assert subprocess.run(["tool"], capture_output=True, check=False).returncode != 0
    environ = {**os.environ, "PATH": str(listed)}
    result = runner.execute(root, runner.Command.of("tool", "cli"), timeout_s=30, environ=environ)
    assert result.status == "pass", result.output


@windows_only("POSIX finds a relative program from the command's directory already")
def test_a_program_named_by_its_path_is_found_from_the_command_s_directory_without_exe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: `CreateProcess` completes a relative name from obelize's directory instead."""
    root = tmp_path / "root"
    (root / ".venv" / "Scripts").mkdir(parents=True)
    program(root / ".venv" / "Scripts" / "tool", passes=True)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        subprocess.run([".venv/Scripts/tool"], cwd=root, capture_output=True, check=False)
    result = runner.execute(
        root, runner.Command.of(".venv/Scripts/tool", "cli"), timeout_s=30, environ=dict(os.environ)
    )
    assert result.status == "pass", result.output


@windows_only("POSIX has no batch files; test_windows_programs.py refuses each spelling there")
@pytest.mark.parametrize(
    ("stored", "spelled"),
    [
        ("tool.bat", "tool.bat"),
        ("tool.cmd", "TOOL.CMD"),
        ("tool.bat", "tool.bat."),
        ("tool.bat", "tool.bat ."),
    ],
    ids=["bat", "upper-case-cmd", "trailing-dot", "trailing-space-and-dot"],
)
def test_a_batch_file_is_refused_however_its_name_is_spelled(
    tmp_path: Path, stored: str, spelled: str
) -> None:
    """Control: Windows drops the trailing dots and spaces and runs the file through `cmd.exe`."""
    marker = tmp_path / "ran"
    (tmp_path / stored).write_bytes(f'@echo ran> "{marker}"\r\n'.encode())
    subprocess.run([str(tmp_path / spelled)], capture_output=True, check=True)
    assert marker.exists()
    marker.unlink()
    result = runner.execute(
        tmp_path,
        runner.Command.of(quoted(tmp_path / spelled), "cli"),
        timeout_s=30,
        environ=dict(os.environ),
    )
    assert (result.status, result.reason) == ("inconclusive", "command_not_executable")
    assert "batch file" in result.output
    assert not marker.exists()


@windows_only("POSIX has no batch files; test_windows_programs.py refuses one there")
def test_a_bare_name_only_a_batch_file_answers_is_refused(tmp_path: Path) -> None:
    """Control: `PATHEXT`, which a shell and `shutil.which` follow, finds the batch file."""
    listed = tmp_path / "listed"
    listed.mkdir()
    marker = tmp_path / "ran"
    (listed / "tool.cmd").write_bytes(f'@echo ran> "{marker}"\r\n'.encode())
    found = shutil.which("tool", path=str(listed))
    assert found is not None
    assert found.casefold().endswith(".cmd")
    environ = {**os.environ, "PATH": str(listed)}
    result = runner.execute(
        tmp_path, runner.Command.of("tool", "cli"), timeout_s=30, environ=environ
    )
    assert (result.status, result.reason) == ("inconclusive", "command_not_executable")
    assert "batch file" in result.output
    assert not marker.exists()


@windows_only("POSIX has no drives; test_windows_programs.py refuses one there")
def test_a_program_relative_to_a_drive_s_current_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: `C:tool` runs the tool in the current directory of `C:`, which is obelize's."""
    program(tmp_path / "tool", passes=False)
    monkeypatch.chdir(tmp_path)
    drive_relative = f"{tmp_path.drive}tool"
    assert subprocess.run([drive_relative], capture_output=True, check=False).returncode != 0
    result = runner.execute(
        tmp_path,
        runner.Command.of(drive_relative, "cli"),
        timeout_s=30,
        environ=dict(os.environ),
    )
    assert (result.status, result.reason) == ("inconclusive", "command_not_executable")
    assert "current directory" in result.output
