"""Benchmark harness: protocol order and grading. Tests swap the process executor for a recorder."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from platforms import BENCH

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import cases  # noqa: E402
import run  # noqa: E402

pytestmark = BENCH

Answer = Callable[[tuple[str, ...], Path], run.Completed]


def completed(
    argv: tuple[str, ...] = ("x",), code: int = 0, out: str = "", late: bool = False
) -> run.Completed:
    return run.Completed(argv, code, 0.0, late, out)


def site(**over: Any) -> dict[str, Any]:
    row = {
        "path": "app.py",
        "line": 1,
        "kind": "import",
        "symbol": "google.generativeai",
        "label": "auto",
    }
    row.update(over)
    return row


def pin(**over: Any) -> dict[str, Any]:
    row = {
        "path": "requirements.txt",
        "line": 1,
        "symbol": "google-generativeai",
        "label": "auto",
    }
    row.update(over)
    return row


def case(**over: Any) -> run.Case:
    fields: dict[str, Any] = {
        "id": "c",
        "origin": "fixture",
        "control": False,
        "split": "dev",
        "repo": None,
        "sha": None,
        "python": None,
        "from_version": None,
        "to_version": None,
        "install": (),
        "test_cmd": None,
        "ground_truth": {
            "call_sites": [],
            "manifests": [],
            "must_not_report": [],
            "tests_cover_change": False,
        },
        "review": {},
        "source": None,
    }
    fields.update(over)
    return run.Case(**fields)


def corpus_case(**over: Any) -> run.Case:
    fields: dict[str, Any] = {
        "id": "owner__repo",
        "origin": "corpus",
        "repo": "https://github.com/owner/repo",
        "sha": "0" * 40,
        "python": "cpython-3.12.9-macos-aarch64-none",
        "from_version": "0.8.6",
        "to_version": "2.24.0",
        "install": ("uv pip install -r requirements.txt",),
        "test_cmd": "python -m pytest -q",
    }
    fields.update(over)
    return case(**fields)


def measured(**over: Any) -> dict[str, Any]:
    table = {
        "detected": 4,
        "false_positive": 0,
        "missed_call_site": 0,
        "unmigrated": 0,
        "patch_applied": True,
        "false_positive_edit": 0,
        "patch_compiles": True,
        "tests_baseline": {"status": "pass", "passed": None, "failed": None, "skipped": None},
        "tests_after": {"status": "pass", "passed": None, "failed": None, "skipped": None},
        "tests_cover_change": True,
        "human_edits": 0,
        "patch_correct": True,
    }
    table.update(over)
    return table


def result(error: Any = None, **over: Any) -> dict[str, Any]:
    return {"error": error, "measurements": measured(**over)}


class Fake:
    """Records every command; answers those a rule matches."""

    def __init__(self, rules: list[tuple[str, Answer]] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.rules = list(rules or [])

    def __call__(self, argv: Any, cwd: Any, env: Any, timeout_s: int) -> run.Completed:
        self.calls.append(tuple(argv))
        for needle, answer in self.rules:
            if needle in " ".join(argv):
                return answer(tuple(argv), Path(cwd))
        return completed(tuple(argv))

    def names(self) -> list[str]:
        return [" ".join(call) for call in self.calls]


def says(code: int = 0, out: str = "", late: bool = False) -> Answer:
    def answer(argv: tuple[str, ...], cwd: Path) -> run.Completed:
        return completed(argv, code, out, late)

    return answer


def prints_versions(mapping: dict[str, str]) -> Answer:

    def answer(argv: tuple[str, ...], cwd: Path) -> run.Completed:
        return completed(argv, 0, f"{mapping[argv[-1]]}\n")

    return answer


# The faked interpreter probe's second line.
BUILD = "3.12.9 (main, Feb 4 2026, 00:00:00) [Clang 17.0.0]"

RUN_JSON = {
    "file_edits": [{"path": "app.py"}, {"path": "requirements.txt"}],
    "withheld": [],
}
PLAN_JSON = {
    "edits": [
        {"path": "app.py", "line": 1, "status": "auto"},
        {"path": "requirements.txt", "line": 1, "status": "auto"},
    ]
}
FINDINGS_JSON = {"findings": [site()]}


def writes_a_run_folder(
    code: int = 6,
    findings: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
    pointer: bool = True,
) -> Answer:
    """`obelize fix`, faked down to the evidence it leaves in the checkout."""

    def answer(argv: tuple[str, ...], cwd: Path) -> run.Completed:
        folder = cwd / ".obelize" / "runs" / "20260921T000000Z-abcdef12"
        folder.mkdir(parents=True)
        (folder / "findings.json").write_text(json.dumps(findings or FINDINGS_JSON))
        (folder / "plan.json").write_text(json.dumps(plan or PLAN_JSON))
        (folder / "run.json").write_text(json.dumps(record or RUN_JSON))
        if pointer:
            (cwd / ".obelize" / "latest").write_text("20260921T000000Z-abcdef12\n")
        return completed(argv, code)

    return answer


def a_whole_run(**over: Any) -> list[tuple[str, Answer]]:
    rules: list[tuple[str, Answer]] = [
        ("obelize.cli", over.get("fix", writes_a_run_folder())),
        (
            "importlib.metadata",
            prints_versions({"google-generativeai": "0.8.6", "google-genai": "2.24.0"}),
        ),
        ("print(sys.executable)", says(0, f"/elsewhere/venv/bin/python\n{BUILD}\n")),
    ]
    for needle, answer in over.get("extra", []):
        rules.insert(0, (needle, answer))
    return rules


def test_shell_reports_what_a_command_said(tmp_path: Path) -> None:
    said = run.shell([sys.executable, "-c", "print('hi')"], tmp_path, {}, 60)
    assert said.exit_code == 0
    assert "hi" in said.output
    assert said.timed_out is False
    assert said.argv[0] == sys.executable


def test_shell_reports_a_non_zero_exit_rather_than_raising(tmp_path: Path) -> None:
    said = run.shell([sys.executable, "-c", "raise SystemExit(3)"], tmp_path, {}, 60)
    assert said.exit_code == 3
    assert said.timed_out is False


def test_shell_captures_stderr_as_well_as_stdout(tmp_path: Path) -> None:
    program = "import sys;sys.stderr.write('boom')"
    assert "boom" in run.shell([sys.executable, "-c", program], tmp_path, {}, 60).output


def test_a_command_that_outlasts_its_ceiling_is_a_timeout(tmp_path: Path) -> None:
    said = run.shell([sys.executable, "-c", "import time;time.sleep(5)"], tmp_path, {}, 1)
    assert said.timed_out is True
    assert said.exit_code == 124


def test_a_program_that_does_not_exist_is_a_fact_about_the_case(tmp_path: Path) -> None:
    said = run.shell(["obelize-not-a-program"], tmp_path, {}, 60)
    assert said.exit_code == 127
    assert said.timed_out is False
    assert said.output


def test_output_that_is_not_utf8_does_not_stop_the_run(tmp_path: Path) -> None:
    program = "import sys;sys.stdout.buffer.write(b'\\xff\\xfe')"
    assert run.shell([sys.executable, "-c", program], tmp_path, {}, 60).exit_code == 0


def test_output_is_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "OUTPUT_CAP", 16)
    said = run.shell([sys.executable, "-c", "print('x' * 1000)"], tmp_path, {}, 60)
    assert len(said.output) == 16


def test_the_offline_executor_refuses_anything_that_could_reach_the_network(tmp_path: Path) -> None:
    execute = run.offline(run.shell)
    with pytest.raises(SystemExit, match="refuses to run git"):
        execute(["git", "fetch"], tmp_path, {}, 60)
    with pytest.raises(SystemExit, match="refuses to run uv"):
        execute(["uv", "pip", "install", "google-genai"], tmp_path, {}, 60)


def test_the_offline_executor_refuses_an_empty_command(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match=r"refuses to run \(nothing\)"):
        run.offline(run.shell)([], tmp_path, {}, 60)


def test_the_offline_executor_still_runs_this_interpreter(tmp_path: Path) -> None:
    said = run.offline(run.shell)([sys.executable, "-c", "print(1)"], tmp_path, {}, 60)
    assert said.exit_code == 0


def test_a_checkout_is_one_commit_deep_and_names_the_sha(tmp_path: Path) -> None:
    built = run.fetch_argv(tmp_path, "https://example.invalid/r.git", "a" * 40)
    assert [argv[3] for argv in built] == ["init", "remote", "fetch", "checkout"]
    assert "--depth" in built[2]
    assert built[2][-1] == "a" * 40
    assert built[1][-1] == "https://example.invalid/r.git"


def test_the_venv_is_built_on_the_full_interpreter_key(tmp_path: Path) -> None:
    built = run.venv_argv(tmp_path / ".venv", "cpython-3.12.9-macos-aarch64-none")
    assert built[:3] == ("uv", "venv", "--python")
    assert built[3] == "cpython-3.12.9-macos-aarch64-none"


def test_a_pin_is_installed_with_two_equals_signs(tmp_path: Path) -> None:
    built = run.pin_argv(tmp_path / "python", "google-genai", "2.24.0")
    assert built[-1] == "google-genai==2.24.0"
    assert "--python" in built


def test_the_version_probe_asks_the_case_interpreter_and_not_uv(tmp_path: Path) -> None:
    built = run.probe_argv(tmp_path / "python", "google-genai")
    assert built[0] == str(tmp_path / "python")
    assert "importlib.metadata" in built[2]
    assert built[-1] == "google-genai"


def test_the_compile_check_writes_no_bytecode(tmp_path: Path) -> None:
    built = run.compile_argv(tmp_path / "python", ["a.py", "b.py"])
    assert "py_compile" not in built[2]
    assert "compile(" in built[2]
    assert built[-2:] == ("a.py", "b.py")


def test_obelize_is_asked_to_apply_and_never_to_verify(tmp_path: Path) -> None:
    built = run.fix_argv(tmp_path)
    assert "--apply" in built
    assert "--non-interactive" in built
    assert "--verify" not in built
    assert built[:3] == (sys.executable, "-m", "obelize.cli")
    assert run.DEFAULT_PACK in built


def test_obelize_is_told_to_consult_no_model_whatever_the_maintainer_configured(
    tmp_path: Path,
) -> None:
    """Else a model the maintainer configured would run on strangers' repositories (ADR-038 D7)."""
    built = run.fix_argv(tmp_path)
    assert built[built.index("--model") + 1] == "none"


def test_a_reviewed_python_means_the_cases_own_interpreter() -> None:
    built = run.suite_argv("python -m pytest -q", None, Path("/case/bin/python"))
    assert built[0] == "/case/bin/python"
    assert built[1:] == ("-m", "pytest", "-q")


def test_a_command_that_is_not_python_is_left_exactly_as_reviewed() -> None:
    assert run.suite_argv("make test", None, Path("/case/bin/python")) == ("make", "test")


def test_a_pytest_run_is_asked_for_a_junit_report() -> None:
    built = run.suite_argv("python -m pytest -q", Path("/j/x.xml"), Path("/p"))
    assert built[-1] == "--junitxml=/j/x.xml"


def test_a_bare_pytest_is_a_pytest_run_too() -> None:
    assert run.suite_argv("pytest -q", Path("/j/x.xml"), Path("/p"))[-1] == "--junitxml=/j/x.xml"


def test_a_command_that_already_asks_for_junit_is_not_asked_twice() -> None:
    built = run.suite_argv("pytest --junitxml=mine.xml", Path("/j/x.xml"), Path("/p"))
    assert built == ("pytest", "--junitxml=mine.xml")


def test_a_command_that_is_not_pytest_gets_no_junit_argument() -> None:
    built = run.suite_argv("python check.py", Path("/j/x.xml"), Path("/p"))
    assert built == ("/p", "check.py")


def test_no_junit_directory_means_no_junit_argument() -> None:
    assert run.suite_argv("pytest -q", None, Path("/p")) == ("pytest", "-q")


def test_every_path_this_harness_chose_is_named_rather_than_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The nearest name wins: the log directory is inside the work root."""
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    checkout = tmp_path / "work" / "round-1" / "owner__repo"
    logs = tmp_path / "work" / "round-1" / "owner__repo.logs"
    said = run.elide(
        (sys.executable, "-m", str(checkout), f"--junitxml={logs}/baseline.xml"),
        checkout,
        logs,
    )
    assert said == ("<harness-python>", "-m", "<case>", "--junitxml=<logs>/baseline.xml")


def test_the_work_root_and_this_checkout_are_both_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    checkout = tmp_path / "work" / "round-1" / "owner__repo"
    said = run.elide((str(checkout), str(tmp_path / "work" / "round-2")), checkout)
    assert said == ("<case>", "<work>/round-2")


def test_a_path_reached_through_a_symlink_is_named_too(tmp_path: Path) -> None:
    """`/var` is a symlink to `/private/var`, so a subprocess prints the other one."""
    (tmp_path / "real" / "owner__repo").mkdir(parents=True)
    (tmp_path / "link").symlink_to(tmp_path / "real")
    checkout = tmp_path / "link" / "owner__repo"
    printed = str(tmp_path / "real" / "owner__repo" / ".venv" / "bin" / "python")
    assert run.elide((printed,), checkout) == ("<case>/.venv/bin/python",)


def test_a_path_this_harness_did_not_choose_is_left_exactly_as_it_was() -> None:
    assert run.elide(("/opt/homebrew/bin/git", "vendor/google/__init__.py")) == (
        "/opt/homebrew/bin/git",
        "vendor/google/__init__.py",
    )


def test_no_step_a_round_records_carries_an_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    record = run.run_case(corpus_case(), execute=Fake(a_whole_run()), fixtures_only=False)
    printed = [argument for step in record["steps"] for argument in step["argv"]]
    assert printed
    for argument in printed:
        assert str(tmp_path) not in argument
        assert str(run.ROOT) not in argument
        assert sys.executable not in argument
    assert str(run.ROOT) not in record["provenance"]["python_executable"]


def test_a_configuration_above_a_checkout_is_found(tmp_path: Path) -> None:
    checkout = tmp_path / "work" / "round-1" / "owner__repo"
    checkout.mkdir(parents=True)
    (tmp_path / "work" / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    assert run.unisolated(checkout) == ["pyproject.toml (2 level(s) up)"]


def test_a_checkouts_own_configuration_is_the_subject_and_not_a_contaminant(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "work" / "round-1" / "owner__repo"
    checkout.mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\n")
    assert run.unisolated(checkout) == []


# Written out: a test iterating the set it pins cannot notice a name leaving.
UPWARD = [
    ".pytest.ini",
    "conftest.py",
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
    "setup.py",
    "tox.ini",
]


def test_every_name_a_tool_searches_upward_for_is_looked_for(tmp_path: Path) -> None:
    checkout = tmp_path / "deep" / "owner__repo"
    checkout.mkdir(parents=True)
    for name in UPWARD:
        (tmp_path / "deep" / name).write_text("")
    found = run.unisolated(checkout)
    assert found == [f"{name} (1 level(s) up)" for name in UPWARD]
    assert set(run.ANCESTOR_CONFIGS) == set(UPWARD)


def test_a_case_whose_work_root_is_somebody_elses_project_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    executor = Fake(a_whole_run())
    record = run.run_case(corpus_case(), execute=executor, fixtures_only=False)
    assert record["error"] == {
        "step": "isolation",
        "reason": "work_root_not_isolated",
        "detail": "pytest.ini (3 level(s) up)",
    }
    assert record["tier"] == "error"
    assert executor.calls == []


def test_the_reason_a_contaminated_work_root_gives_is_in_the_closed_set() -> None:
    assert "work_root_not_isolated" in run.ERROR_REASONS


def test_the_work_tree_is_outside_this_repository() -> None:
    assert run.ROOT not in run.WORK.resolve().parents
    assert run.WORK.resolve() != run.ROOT.resolve()


def test_the_version_is_the_last_thing_the_probe_printed() -> None:
    assert run.observed_version(completed(out="warning\n0.8.6\n")) == "0.8.6"


def test_a_probe_that_failed_reports_no_version() -> None:
    assert run.observed_version(completed(code=1, out="0.8.6")) is None


def test_a_probe_that_printed_nothing_reports_no_version() -> None:
    assert run.observed_version(completed(out="  \n")) is None


def test_the_pin_that_was_asked_for_is_the_pin_that_has_to_be_there() -> None:
    assert run.mismatch("google-genai", "2.24.0", "2.24.0") is None


def test_an_installed_version_that_is_not_the_pin_is_named() -> None:
    said = run.mismatch("google-genai", "2.24.0", "1.47.0")
    assert said is not None
    assert "pinned 2.24.0" in said
    assert "installed 1.47.0" in said


def test_a_post_release_of_the_pin_is_not_the_pin() -> None:
    assert run.mismatch("google-genai", "2.24.0", "2.24.0.post1") is not None


def test_a_venv_that_cannot_be_asked_is_a_mismatch_and_not_a_pass() -> None:
    said = run.mismatch("google-genai", "2.24.0", None)
    assert said is not None
    assert "could not be asked" in said


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (None, "not_run"),
        (completed(code=0), "pass"),
        (completed(code=1), "fail"),
        (completed(code=124, late=True), "inconclusive"),
    ],
)
def test_what_a_test_phase_said(given: Any, expected: str) -> None:
    assert run.suite_status(given) == expected


def test_a_timeout_is_inconclusive_even_when_the_code_looks_like_a_pass() -> None:
    assert run.suite_status(completed(code=0, late=True)) == "inconclusive"


PYTEST_ARGV = ("/v/bin/python", "-m", "pytest", "tests", "-q", "--junitxml=/l/baseline.xml")


@pytest.mark.parametrize(
    ("code", "said"),
    [
        (0, "pass"),
        (1, "fail"),
        (2, "inconclusive"),
        (3, "inconclusive"),
        (4, "inconclusive"),
        (5, "inconclusive"),
        (137, "inconclusive"),
    ],
)
def test_a_pytest_run_is_read_against_pytests_own_exit_codes(code: int, said: str) -> None:
    """Only `1` means the tests failed; every other non-zero code is no verdict."""
    assert run.suite_status(completed(PYTEST_ARGV, code)) == said


@pytest.mark.parametrize(
    ("code", "said"),
    [(0, "pass"), (1, "fail"), (4, "fail"), (5, "fail")],
)
def test_a_command_that_is_not_pytest_is_read_the_way_a_shell_reads_one(
    code: int, said: str
) -> None:
    assert run.suite_status(completed(("make", "test"), code)) == said


# pytest's junit report when a test module cannot be imported: exit `2`, one test in error.
COLLECTION_ERROR = (
    '<testsuites><testsuite name="pytest" errors="1" failures="0" skipped="0" tests="1">'
    '<testcase classname="" name="test_app"><error message="collection failure"/></testcase>'
    "</testsuite></testsuites>"
)


@pytest.mark.parametrize(
    ("code", "failed", "said"),
    [(2, 1, "fail"), (2, 0, "inconclusive"), (2, None, "inconclusive"), (3, 1, "inconclusive")],
)
def test_a_collection_error_the_report_counts_is_a_failure(
    code: int, failed: int | None, said: str
) -> None:
    """`2` with a counted error means an import failed; `2` without one, or `3`, is no verdict."""
    assert run.suite_status(completed(PYTEST_ARGV, code), failed) == said


def test_a_migration_that_breaks_the_import_under_test_is_wrong(tmp_path: Path) -> None:
    (tmp_path / "after.xml").write_text(COLLECTION_ERROR, encoding="utf-8")
    after = run._phase_result(completed(PYTEST_ARGV, 2), tmp_path, "after")
    assert after == {"status": "fail", "passed": 0, "failed": 1, "skipped": 0}
    assert run.tier(result(tests_after=after)) == "wrong"


def test_a_regression_is_not_blamed_on_a_tool_that_wrote_nothing() -> None:
    """The after-run also swaps the SDK, so on an unedited tree a failure is the swap's fault."""
    failing = {"status": "fail", "passed": 0, "failed": 1, "skipped": 0}
    refused = result(
        patch_applied=False, patch_compiles=None, patch_correct=None, tests_after=failing
    )
    assert run.tier(refused) == "unsupported"


def test_a_bare_pytest_program_is_a_pytest_run_here_too() -> None:
    assert run.suite_status(completed(("pytest", "-q"), 5)) == "inconclusive"


def test_a_suite_that_produced_no_verdict_after_the_patch_is_not_a_regression() -> None:
    """Reading a usage error as `fail` would grade a repository broken for pytest's parser."""
    inconclusive = run.tier(
        result(
            tests_after={
                "status": "inconclusive",
                "passed": None,
                "failed": None,
                "skipped": None,
            },
            human_edits=None,
        )
    )
    assert inconclusive == "patched_unverified"
    failed = run.tier(
        result(tests_after={"status": "fail", "passed": None, "failed": None, "skipped": None})
    )
    assert failed == "wrong"


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="2" skipped="3" tests="10">
</testsuite></testsuites>
"""


def test_junit_counts_are_read_off_the_report(tmp_path: Path) -> None:
    report = tmp_path / "after.xml"
    report.write_text(JUNIT)
    assert run.junit_counts(report) == (4, 3, 3)


def test_a_command_that_wrote_no_report_has_no_counts(tmp_path: Path) -> None:
    assert run.junit_counts(tmp_path / "missing.xml") == (None, None, None)


def test_a_report_that_does_not_parse_has_no_counts(tmp_path: Path) -> None:
    report = tmp_path / "after.xml"
    report.write_text("<testsuite")
    assert run.junit_counts(report) == (None, None, None)


def test_only_call_site_kinds_enter_the_rate() -> None:
    subject = case(
        ground_truth={
            "call_sites": [site(), site(line=2, kind="dynamic")],
            "manifests": [pin()],
            "tests_cover_change": False,
        }
    )
    assert sum(run.key_rows(subject).values()) == 1


def test_every_row_the_key_names_has_to_be_migrated_including_the_string_ones() -> None:
    subject = case(
        ground_truth={
            "call_sites": [site(), site(line=2, kind="dynamic")],
            "manifests": [pin()],
            "tests_cover_change": False,
        }
    )
    assert len(run.expected_rows(subject)) == 3
    assert ("requirements.txt", 1, "google-generativeai") in run.expected_rows(subject)


def test_an_edit_counts_only_when_its_file_was_written() -> None:
    plan = {"edits": [{"path": "app.py", "line": 1, "status": "auto"}]}
    assert run.applied_positions(plan, []) == {}
    assert run.applied_positions(plan, ["app.py"])[("app.py", 1)] == 1


def test_an_edit_the_rules_withheld_is_not_an_applied_edit() -> None:
    plan = {"edits": [{"path": "app.py", "line": 1, "status": "needs_review"}]}
    assert run.applied_positions(plan, ["app.py"]) == {}


def test_a_withheld_row_with_no_symbol_is_still_a_row() -> None:
    assert run.withheld_rows({"withheld": [{"path": "a.py", "line": 1, "symbol": None}]}) == {
        ("a.py", 1, "")
    }


def test_two_rows_on_one_line_are_not_one_row() -> None:
    """The `requirements.txt` shape: one pin applied, one withheld, same line."""
    subject = case(
        ground_truth={"call_sites": [], "manifests": [pin()], "tests_cover_change": False}
    )
    plan = {"edits": [{"path": "requirements.txt", "line": 1, "status": "auto"}]}
    record = {
        "file_edits": [{"path": "requirements.txt"}],
        "withheld": [{"path": "requirements.txt", "line": 1, "symbol": "google-generativeai"}],
    }
    assert run.unmigrated(subject, plan, record) == 1


def test_a_row_nobody_reported_is_unmigrated_too() -> None:
    subject = case(
        ground_truth={"call_sites": [site(line=9)], "manifests": [], "tests_cover_change": False}
    )
    assert run.unmigrated(subject, {"edits": []}, {"file_edits": [], "withheld": []}) == 1


def test_a_row_that_was_neither_refused_nor_missed_is_migrated() -> None:
    subject = case(
        ground_truth={"call_sites": [site()], "manifests": [], "tests_cover_change": False}
    )
    assert run.unmigrated(subject, PLAN_JSON, RUN_JSON) == 0


def test_the_measurement_table_is_filled_from_one_run_folder() -> None:
    subject = case(
        ground_truth={
            "call_sites": [
                site(),
                site(line=2, kind="call", symbol="google.generativeai.configure"),
            ],
            "manifests": [],
            "tests_cover_change": False,
        }
    )
    table = run.measure(subject, [site()], PLAN_JSON, RUN_JSON)
    assert table["detected"] == 1
    assert table["missed_call_site"] == 1
    assert table["false_positive"] == 0
    assert table["patch_applied"] is True


def test_an_edit_the_key_never_named_is_a_false_positive_edit() -> None:
    subject = case(ground_truth={"call_sites": [], "manifests": [], "tests_cover_change": False})
    table = run.measure(subject, [], PLAN_JSON, RUN_JSON)
    assert table["false_positive_edit"] == 2
    assert table["detected"] == 0


def test_a_finding_the_key_does_not_have_is_a_false_positive() -> None:
    subject = case(ground_truth={"call_sites": [], "manifests": [], "tests_cover_change": False})
    table = run.measure(subject, [site()], {"edits": []}, {"file_edits": [], "withheld": []})
    assert table["false_positive"] == 1
    assert table["detected"] == 1


def test_every_tier_is_reachable_and_they_are_the_documented_six() -> None:
    reached = {
        run.tier(result(error={"step": "fetch", "reason": "fetch_failed", "detail": ""})),
        run.tier(result(patch_compiles=False)),
        run.tier(result(patch_applied=False)),
        run.tier(result(unmigrated=2)),
        run.tier(result()),
        run.tier(result(human_edits=None)),
    }
    assert reached == set(run.TIERS)


def test_an_error_outranks_everything_else() -> None:
    record = result(
        error={"step": "venv", "reason": "venv_failed", "detail": ""},
        patch_applied=False,
        unmigrated=9,
    )
    assert run.tier(record) == "error"


def test_a_patch_that_does_not_compile_is_wrong() -> None:
    assert run.tier(result(patch_compiles=False)) == "wrong"


def test_a_reviewer_who_says_the_patch_is_wrong_is_believed() -> None:
    assert run.tier(result(patch_correct=False)) == "wrong"


def test_an_edit_the_key_never_named_is_wrong() -> None:
    assert run.tier(result(false_positive_edit=1)) == "wrong"


def test_a_suite_that_passed_before_and_fails_after_is_wrong() -> None:
    record = result(tests_after={"status": "fail", "passed": None, "failed": 1})
    assert run.tier(record) == "wrong"


def test_a_suite_that_was_already_failing_is_not_a_regression() -> None:
    record = result(
        tests_baseline={"status": "fail", "passed": None, "failed": 1},
        tests_after={"status": "fail", "passed": None, "failed": 1},
    )
    assert run.tier(record) == "patched_unverified"


def test_a_patch_that_was_never_written_is_the_tool_refusing() -> None:
    assert run.tier(result(patch_applied=False, unmigrated=6)) == "unsupported"


def test_a_row_the_run_left_behind_makes_it_partial() -> None:
    assert run.tier(result(unmigrated=1)) == "partial"


def test_a_complete_migration_nobody_has_read_is_not_a_verified_success() -> None:
    assert run.tier(result(human_edits=None)) == "patched_unverified"


def test_a_human_who_wrote_one_hunk_is_not_zero_hunks() -> None:
    assert run.tier(result(human_edits=1)) == "patched_unverified"


@pytest.mark.parametrize(
    "short",
    [
        {"false_positive": 1},
        {"missed_call_site": 1},
        {"tests_baseline": {"status": "not_run", "passed": None, "failed": None}},
        {"tests_after": {"status": "inconclusive", "passed": None, "failed": None}},
        {"tests_cover_change": False},
    ],
)
def test_each_thing_verified_success_asks_for_is_asked_for(short: dict[str, Any]) -> None:
    assert run.tier(result()) == "verified_success"
    assert run.tier(result(**short)) == "patched_unverified"


def test_a_suite_that_ran_no_test_verifies_nothing() -> None:
    """Round one has a suite that passes while skipping 19 of its 21 tests."""
    skipped_everything = result(
        tests_after={"status": "pass", "passed": 0, "failed": 0, "skipped": 19}
    )
    assert run.tier(skipped_everything) == "patched_unverified"
    ran_one = result(tests_after={"status": "pass", "passed": 1, "failed": 0, "skipped": 19})
    assert run.tier(ran_one) == "verified_success"


def test_a_suite_with_no_report_to_read_is_judged_on_its_status_alone() -> None:
    """A test command that is not pytest writes no junit, and `clean` is one."""
    no_counts = result(
        tests_after={"status": "pass", "passed": None, "failed": None, "skipped": None}
    )
    assert run.tier(no_counts) == "verified_success"


def all_auto() -> dict[str, Any]:
    return {
        "call_sites": [site()],
        "manifests": [pin()],
        "must_not_report": [],
        "tests_cover_change": True,
    }


def test_a_case_whose_every_row_is_auto_and_whose_suite_runs_can_reach_the_headline() -> None:
    assert run.ceiling(case(ground_truth=all_auto(), test_cmd="pytest -q")) is None


def test_a_control_is_excluded_from_the_rate_and_says_so() -> None:
    subject = case(control=True, ground_truth=all_auto(), test_cmd="pytest -q")
    assert run.ceiling(subject) == "a negative control is excluded from the rate"


def test_a_case_whose_key_names_nothing_cannot_reach_the_headline() -> None:
    empty = {"call_sites": [], "manifests": [], "tests_cover_change": True}
    assert run.ceiling(case(ground_truth=empty, test_cmd="pytest -q")) == (
        "the key names nothing to migrate"
    )


def test_a_case_with_no_test_command_cannot_reach_the_headline() -> None:
    assert run.ceiling(case(ground_truth=all_auto())) == "no test command"


def test_a_suite_that_does_not_cover_the_change_cannot_reach_the_headline() -> None:
    truth = {**all_auto(), "tests_cover_change": False}
    assert run.ceiling(case(ground_truth=truth, test_cmd="pytest -q")) == (
        "the tests do not cover the change"
    )


def test_a_manual_row_caps_a_case_below_the_headline() -> None:
    truth = {**all_auto(), "call_sites": [site(label="manual", why="somebody decides")]}
    assert run.ceiling(case(ground_truth=truth, test_cmd="pytest -q")) == (
        "a row the key marks `manual`"
    )


def test_a_manual_manifest_row_caps_a_case_too() -> None:
    truth = {**all_auto(), "manifests": [pin(label="manual", why="nothing migrated")]}
    assert run.ceiling(case(ground_truth=truth, test_cmd="pytest -q")) is not None


def test_a_row_the_pack_flags_rather_than_edits_caps_a_case() -> None:
    truth = {**all_auto(), "call_sites": [site(kind="dynamic")]}
    assert run.ceiling(case(ground_truth=truth, test_cmd="pytest -q")) == (
        "a row the pack flags rather than edits"
    )


def test_the_published_ceiling_over_the_round_is_the_one_the_document_prints() -> None:
    """Round 1 cannot produce a verified success: no graded case is uncapped."""
    graded = [subject for subject in run.corpus() if not subject.control]
    assert len(graded) == 20
    assert [subject.id for subject in graded if run.ceiling(subject) is None] == []
    assert sum(1 for s in graded if run.ceiling(s) == "no test command") == 16
    assert sum(1 for s in graded if run.ceiling(s) == "a row the key marks `manual`") == 3
    capped = [s.id for s in graded if run.ceiling(s) == "a row the pack flags rather than edits"]
    assert capped == ["navamai__navamai"]


def test_the_round_is_every_case_and_every_control() -> None:
    loaded = run.corpus()
    assert len(loaded) == 23
    assert sum(1 for subject in loaded if subject.control) == 3
    assert {subject.origin for subject in loaded} == {"corpus"}


def test_a_case_carries_the_pins_and_the_full_interpreter_key() -> None:
    subject = next(s for s in run.corpus() if s.id == "navamai__navamai")
    assert subject.from_version == "0.8.6"
    assert subject.to_version == "2.24.0"
    assert subject.python == "cpython-3.12.9-macos-aarch64-none"
    assert subject.split == "holdout"
    assert subject.test_cmd == "python -m pytest tests/test_gemini.py -q"


def test_a_control_has_no_side_and_an_empty_key() -> None:
    control = next(s for s in run.corpus() if s.control)
    assert control.split is None
    assert control.ground_truth["call_sites"] == []
    assert control.id == control.id.replace("/", "__")
    assert "__" in control.id


def test_the_four_fixtures_are_the_ones_committed() -> None:
    assert [subject.id for subject in run.fixtures()] == [
        "clean",
        "control-migrated",
        "mixed",
        "withheld",
    ]
    assert {subject.origin for subject in run.fixtures()} == {"fixture"}


def test_a_fixture_pins_nothing_and_names_no_interpreter() -> None:
    clean = run.fixtures()[0]
    assert clean.from_version is None
    assert clean.to_version is None
    assert clean.python is None
    assert clean.source is not None
    assert clean.source.name == "repo"
    assert clean.review["human_edits"] == 0


def a_session(tmp_path: Path, execute: Any) -> run.Session:
    return run.Session(case(), execute, tmp_path, tmp_path / "logs", {})


def test_a_step_is_recorded_with_its_command_and_its_code(tmp_path: Path) -> None:
    session = a_session(tmp_path, Fake([("x", says(3, "said"))]))
    said = session.do(5, "baseline", ["x"], timeout_s=1, reason=None)
    assert said.exit_code == 3
    assert session.steps[0].name == "baseline"
    assert session.steps[0].number == 5
    assert session.error is None


def test_a_steps_output_is_written_where_it_is_never_published(tmp_path: Path) -> None:
    session = a_session(tmp_path, Fake([("x", says(0, "the suite said this"))]))
    session.do(5, "baseline", ["x"], timeout_s=1, reason=None)
    written = list((tmp_path / "logs").iterdir())
    assert [path.name for path in written] == ["01-baseline.log"]
    assert "the suite said this" in written[0].read_text()


def test_a_required_step_that_failed_stops_the_case(tmp_path: Path) -> None:
    session = a_session(tmp_path, Fake([("x", says(1))]))
    with pytest.raises(run.StepError):
        session.do(1, "fetch", ["x"], timeout_s=1, reason="fetch_failed")
    assert session.error == {
        "step": "fetch",
        "reason": "fetch_failed",
        "detail": "fetch exited 1",
    }


def test_a_required_step_that_outlasted_its_ceiling_is_a_timeout_and_not_its_reason(
    tmp_path: Path,
) -> None:
    session = a_session(tmp_path, Fake([("x", says(124, late=True))]))
    with pytest.raises(run.StepError):
        session.do(3, "install", ["x"], timeout_s=7, reason="install_failed")
    assert session.error is not None
    assert session.error["reason"] == "timeout"
    assert "7s" in session.error["detail"]


def test_a_step_whose_exit_code_is_the_measurement_never_fails_the_case(tmp_path: Path) -> None:
    session = a_session(tmp_path, Fake([("x", says(1, late=True))]))
    session.do(5, "baseline", ["x"], timeout_s=1, reason=None)
    assert session.error is None


STEPS = [
    "fetch",
    "fetch",
    "fetch",
    "fetch",
    "venv",
    "resolve",
    "install",
    "install-from",
    "install-from-check",
    "baseline",
    "fix",
    "compile",
    "install-to",
    "install-to-check",
    "after",
]


def test_the_protocol_runs_its_steps_in_the_order_the_document_gives_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    fake = Fake(a_whole_run())
    record = run.run_case(corpus_case(), execute=fake, fixtures_only=False)
    assert [step["name"] for step in record["steps"]] == STEPS
    assert [step["number"] for step in record["steps"]] == [
        1,
        1,
        1,
        1,
        2,
        2,
        3,
        4,
        4,
        5,
        6,
        6,
        7,
        7,
        8,
    ]
    assert record["error"] is None


def test_the_from_sdk_is_installed_before_the_baseline_and_the_to_sdk_after_the_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    fake = Fake(a_whole_run())
    run.run_case(corpus_case(), execute=fake, fixtures_only=False)
    order = fake.names()
    from_at = next(i for i, line in enumerate(order) if "google-generativeai==0.8.6" in line)
    to_at = next(i for i, line in enumerate(order) if "google-genai==2.24.0" in line)
    fix_at = next(i for i, line in enumerate(order) if "obelize.cli" in line)
    baseline_at = next(i for i, line in enumerate(order) if "-m pytest" in line)
    assert from_at < baseline_at < fix_at < to_at


def test_the_resolved_interpreter_and_the_machine_are_in_the_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    record = run.run_case(corpus_case(), execute=Fake(a_whole_run()), fixtures_only=False)
    provenance = record["provenance"]
    assert provenance["python_executable"] == "/elsewhere/venv/bin/python"
    assert provenance["python_build"] == BUILD
    assert provenance["python"] == "cpython-3.12.9-macos-aarch64-none"
    assert provenance["machine"]
    assert provenance["os"]
    assert provenance["sdk_from"] == "0.8.6"
    assert provenance["sdk_to"] == "2.24.0"
    assert len(provenance["pack_sha256"]) == 64
    assert provenance["spec_sha256"] != provenance["pack_sha256"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", provenance["run_at"])


def test_the_interpreter_probe_asks_for_the_path_and_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    executor = Fake(a_whole_run())
    run.run_case(corpus_case(), execute=executor, fixtures_only=False)
    probe = next(call for call in executor.names() if "print(sys.executable)" in call)
    assert probe.endswith(
        "-c import sys;print(sys.executable);print(' '.join(sys.version.split()))"
    )


def test_a_venv_that_prints_no_path_falls_back_to_the_one_it_was_built_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    rules = a_whole_run(extra=[("print(sys.executable)", says(0, "\n"))])
    record = run.run_case(corpus_case(), execute=Fake(rules), fixtures_only=False)
    assert record["provenance"]["python_executable"] == (
        "<work>/round-1/owner__repo/.venv/bin/python"
    )
    assert record["provenance"]["python_build"] is None


def test_a_venv_that_named_itself_but_not_its_build_is_the_same_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path without its build is half an answer: the build is what the field is for."""
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    rules = a_whole_run(extra=[("print(sys.executable)", says(0, "/elsewhere/python\n"))])
    record = run.run_case(corpus_case(), execute=Fake(rules), fixtures_only=False)
    assert record["provenance"]["python_executable"].endswith(".venv/bin/python")
    assert record["provenance"]["python_build"] is None


@pytest.mark.parametrize(
    ("needle", "reason"),
    [
        ("fetch", "fetch_failed"),
        ("uv venv", "venv_failed"),
        ("uv pip install -r", "install_failed"),
        ("google-generativeai==0.8.6", "install_failed"),
    ],
)
def test_a_step_the_protocol_needs_fails_the_case_with_its_own_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, needle: str, reason: str
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    rules = a_whole_run(extra=[(needle, says(1))])
    subject = corpus_case(
        ground_truth={"call_sites": [site()], "manifests": [pin()], "tests_cover_change": True}
    )
    record = run.run_case(subject, execute=Fake(rules), fixtures_only=False)
    assert record["tier"] == "error"
    assert record["error"]["reason"] == reason
    # A case that never ran measured nothing, not two unmigrated rows.
    assert record["measurements"]["detected"] == 0
    assert record["measurements"]["unmigrated"] == 0
    assert record["measurements"]["patch_applied"] is False


def test_an_installed_version_that_is_not_the_pin_fails_the_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    wrong = prints_versions({"google-generativeai": "0.8.5", "google-genai": "2.24.0"})
    record = run.run_case(
        corpus_case(),
        execute=Fake(a_whole_run(extra=[("importlib.metadata", wrong)])),
        fixtures_only=False,
    )
    assert record["tier"] == "error"
    assert record["error"]["reason"] == "version_mismatch"
    assert record["error"]["step"] == "install-from-check"
    assert "installed 0.8.5" in record["error"]["detail"]
    assert [step["name"] for step in record["steps"]][-1] == "install-from-check"


def test_a_mismatched_to_pin_fails_the_case_after_the_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    wrong = prints_versions({"google-generativeai": "0.8.6", "google-genai": "1.47.0"})
    record = run.run_case(
        corpus_case(),
        execute=Fake(a_whole_run(extra=[("importlib.metadata", wrong)])),
        fixtures_only=False,
    )
    assert record["error"]["step"] == "install-to-check"
    assert record["tier"] == "error"


def test_a_probe_that_could_not_run_fails_the_case_rather_than_being_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    rules = a_whole_run(extra=[("importlib.metadata", says(1, "no such distribution"))])
    record = run.run_case(corpus_case(), execute=Fake(rules), fixtures_only=False)
    assert record["error"]["reason"] == "version_mismatch"


def test_obelize_exiting_something_the_contract_does_not_allow_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    rules = a_whole_run(fix=writes_a_run_folder(code=2))
    record = run.run_case(corpus_case(), execute=Fake(rules), fixtures_only=False)
    assert record["error"] == {
        "step": "fix",
        "reason": "obelize_failed",
        "detail": "obelize fix exited 2",
    }


@pytest.mark.parametrize("code", [0, 4, 6])
def test_the_three_codes_an_apply_is_allowed_to_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    rules = a_whole_run(fix=writes_a_run_folder(code=code))
    record = run.run_case(corpus_case(), execute=Fake(rules), fixtures_only=False)
    assert record["error"] is None


def test_obelize_outlasting_its_ceiling_is_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    rules = a_whole_run(extra=[("obelize.cli", says(124, late=True))])
    record = run.run_case(corpus_case(), execute=Fake(rules), fixtures_only=False)
    assert record["error"]["reason"] == "timeout"


def test_an_apply_that_left_no_run_folder_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    rules = a_whole_run(fix=writes_a_run_folder(pointer=False))
    record = run.run_case(corpus_case(), execute=Fake(rules), fixtures_only=False)
    assert record["error"]["reason"] == "no_run_folder"


def test_a_latest_that_is_not_a_regular_file_fails_the_case_and_not_the_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.obelize/latest` is a regular file; reading a directory would raise."""
    monkeypatch.setattr(run, "WORK", tmp_path / "work")

    def answer(argv: tuple[str, ...], cwd: Path) -> run.Completed:
        (cwd / ".obelize" / "latest").mkdir(parents=True)
        return completed(argv, 6)

    record = run.run_case(corpus_case(), execute=Fake(a_whole_run(fix=answer)), fixtures_only=False)
    assert record["error"]["reason"] == "no_run_folder"
    assert record["tier"] == "error"


def test_a_run_folder_missing_a_document_is_read_as_an_empty_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")

    def answer(argv: tuple[str, ...], cwd: Path) -> run.Completed:
        (cwd / ".obelize" / "runs" / "r").mkdir(parents=True)
        (cwd / ".obelize" / "latest").write_text("r\n")
        return completed(argv, 4)

    record = run.run_case(corpus_case(), execute=Fake(a_whole_run(fix=answer)), fixtures_only=False)
    assert record["measurements"]["patch_applied"] is False
    assert record["measurements"]["patch_compiles"] is None
    assert record["tier"] == "unsupported"


def test_a_patch_that_does_not_compile_is_recorded_as_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    rules = a_whole_run(extra=[("compile(", says(1, "SyntaxError"))])
    record = run.run_case(corpus_case(), execute=Fake(rules), fixtures_only=False)
    assert record["measurements"]["patch_compiles"] is False
    assert record["tier"] == "wrong"


def test_only_python_files_are_compiled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    fake = Fake(a_whole_run())
    run.run_case(corpus_case(), execute=fake, fixtures_only=False)
    compiled = next(call for call in fake.calls if "compile(" in " ".join(call))
    assert compiled[-1] == "app.py"
    assert "requirements.txt" not in compiled


def test_a_case_with_no_test_command_runs_neither_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    record = run.run_case(
        corpus_case(test_cmd=None), execute=Fake(a_whole_run()), fixtures_only=False
    )
    names = [step["name"] for step in record["steps"]]
    assert "baseline" not in names
    assert "after" not in names
    assert record["measurements"]["tests_baseline"]["status"] == "not_run"


def test_a_junit_report_becomes_the_passed_and_failed_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")

    def answer(argv: tuple[str, ...], cwd: Path) -> run.Completed:
        report = Path(argv[-1].split("=", 1)[1])
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(JUNIT)
        return completed(argv, 0)

    rules = a_whole_run(extra=[("-m pytest", answer)])
    record = run.run_case(corpus_case(), execute=Fake(rules), fixtures_only=False)
    assert record["measurements"]["tests_after"] == {
        "status": "pass",
        "passed": 4,
        "failed": 3,
        "skipped": 3,
    }


def test_a_case_run_twice_starts_from_the_same_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    first = run.run_case(corpus_case(), execute=Fake(a_whole_run()), fixtures_only=False)
    second = run.run_case(corpus_case(), execute=Fake(a_whole_run()), fixtures_only=False)
    assert run.comparable(first) == run.comparable(second)


def test_the_fixtures_pass_runs_the_offline_protocol_and_agrees_with_its_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    assert run.fixtures_pass(run.offline(run.shell)) == 0
    printed = capsys.readouterr().out
    assert "clean: verified_success" in printed
    assert "mixed: partial" in printed
    assert "withheld: unsupported" in printed
    assert "control-migrated: unsupported" in printed
    assert "0 mismatch(es)" in printed


def test_a_fixture_whose_result_moved_fails_the_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    only = [subject for subject in run.fixtures() if subject.id == "withheld"]
    monkeypatch.setattr(run, "fixtures", lambda: only)
    moved = {**run.expected(only[0]), "tier": "verified_success"}
    monkeypatch.setattr(run, "expected", lambda subject: moved)
    assert run.fixtures_pass(run.offline(run.shell)) == 1
    printed = capsys.readouterr().out
    assert "withheld: tier:" in printed
    assert "MISMATCH" in printed


def test_a_fixture_is_migrated_in_a_copy_and_never_where_it_is_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    before = (run.FIXTURES / "clean" / "repo" / "app.py").read_text()
    run.run_case(run.fixtures()[0], execute=run.offline(run.shell), fixtures_only=True)
    assert (run.FIXTURES / "clean" / "repo" / "app.py").read_text() == before
    assert not (run.FIXTURES / "clean" / "repo" / ".obelize").exists()
    assert "from google import genai" in (tmp_path / "work/fixtures/clean/app.py").read_text()


def test_a_fixture_records_the_interpreter_that_actually_ran_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no venv offline, so the harness's own interpreter is the case's."""
    monkeypatch.setattr(run, "WORK", tmp_path / "work")
    record = run.run_case(run.fixtures()[0], execute=run.offline(run.shell), fixtures_only=True)
    assert record["provenance"]["python_executable"] == "<harness-python>"
    assert record["provenance"]["python_build"] == " ".join(sys.version.split())


def test_the_comparison_drops_everything_a_clock_touched() -> None:
    record = {
        "tier": "partial",
        "error": None,
        "measurements": {"detected": 1, "runtime_seconds": 9.9, "tests_cover_change": True},
        "steps": [{"name": "fix", "exit_code": 4, "duration_s": 3.3}],
    }
    assert run.comparable(record) == {
        "tier": "partial",
        "error": None,
        "measurements": {"detected": 1},
        "steps": [["fix", 4]],
    }


def test_a_difference_is_named_rather_than_diffed() -> None:
    got: dict[str, Any] = {
        "tier": "wrong",
        "error": None,
        "steps": [["fix", 1]],
        "measurements": {"detected": 2},
    }
    want = {
        "tier": "partial",
        "error": None,
        "steps": [["fix", 4]],
        "measurements": {"detected": 3},
    }
    assert run.differences(got, want) == [
        "tier: 'wrong' != 'partial'",
        "steps: [['fix', 1]] != [['fix', 4]]",
        "measurements.detected: 2 != 3",
    ]


def test_a_measurement_only_one_side_has_is_a_difference() -> None:
    got: dict[str, Any] = {"tier": "a", "error": None, "steps": [], "measurements": {"new": 1}}
    want: dict[str, Any] = {"tier": "a", "error": None, "steps": [], "measurements": {}}
    assert run.differences(got, want) == ["measurements.new: 1 != None"]


def test_two_identical_records_differ_in_nothing() -> None:
    same: dict[str, Any] = {"tier": "a", "error": None, "steps": [], "measurements": {"x": 1}}
    assert run.differences(same, same) == []


def test_a_round_writes_one_result_file_per_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(run, "corpus", lambda: [corpus_case(id="only")])
    monkeypatch.setattr(
        run, "run_case", lambda subject, **_: {"case": subject.id, "tier": "partial"}
    )
    assert run.round_pass(None) == 0
    written = tmp_path / "results" / f"round-{cases.load().cases['round']}" / "only.json"
    assert json.loads(written.read_text())["tier"] == "partial"
    assert "only: partial" in capsys.readouterr().out


def test_a_round_can_be_asked_for_one_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(run, "corpus", lambda: [corpus_case(id="a"), corpus_case(id="b")])
    monkeypatch.setattr(run, "run_case", lambda subject, **_: {"case": subject.id, "tier": "error"})
    assert run.round_pass("b") == 0
    folder = tmp_path / "results" / f"round-{cases.load().cases['round']}"
    assert [path.name for path in folder.iterdir()] == ["b.json"]


def test_a_case_nobody_defined_is_a_failure_and_not_an_empty_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(run, "corpus", lambda: [corpus_case(id="a")])
    assert run.round_pass("nope") == 1
    assert "no case named nope" in capsys.readouterr().out


def test_the_round_directory_is_named_by_the_round_and_not_by_a_flag() -> None:
    assert run._round_name() == f"round-{cases.load().cases['round']}"


def test_fixtures_only_gets_an_executor_that_refuses_the_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[Any] = []

    def remember(execute: Any) -> int:
        seen.append(execute)
        return 0

    monkeypatch.setattr(run, "fixtures_pass", remember)
    assert run.main(["--fixtures-only"]) == 0
    with pytest.raises(SystemExit, match="refuses to run git"):
        seen[0](["git", "fetch"], tmp_path, {}, 1)


def test_the_two_modes_are_two_runs_and_not_one(capsys: pytest.CaptureFixture[str]) -> None:
    assert run.main(["--fixtures-only", "--case", "x"]) == 2
    assert "different runs" in capsys.readouterr().out


def test_with_no_flags_the_round_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[Any] = []

    def remember(only: Any) -> int:
        asked.append(only)
        return 0

    monkeypatch.setattr(run, "round_pass", remember)
    assert run.main([]) == 0
    assert run.main(["--case", "x"]) == 0
    assert asked == [None, "x"]


def test_the_commit_is_recorded_and_its_absence_is_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run._commit() is not None
    monkeypatch.setattr(run, "ROOT", tmp_path)
    assert run._commit() is None
