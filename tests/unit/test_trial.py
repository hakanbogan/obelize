"""`obelize.trial`: a copy, two environments from local wheels, and the tests run in each."""

from __future__ import annotations

import json
import os
import shutil
import sys
import sysconfig
from typing import TYPE_CHECKING

import pytest
from packaging.version import Version

import fakeindex
from obelize import gitutil
from obelize.models import CommandResult
from obelize.trial import copy, envs, run, tests
from support import committed, git

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv makes the environments")
PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"
WHEEL = "Wheel-Version: 1.0\nGenerator: t\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
V1 = "VERSION = '1.0'\n\ndef old_greet(name):\n    return name\n"
V2 = "VERSION = '2.0'\n\ndef greet(name):\n    return name\n"
APP = "import acme_kit\n\n\ndef hello(name):\n    return acme_kit.old_greet(name)\n"
TEST = (
    "import app\n\n\ndef test_hello():\n    assert app.hello('x') == 'x'\n\n\n"
    "def test_twice():\n    assert app.hello('y') == 'y'\n"
)


@pytest.fixture
def links(tmp_path: Path) -> Path:
    """A directory of wheels of an invented library, which uv installs from and nothing else."""
    where = tmp_path / "links"
    where.mkdir()
    (where / "acme_new-1.0-py3-none-any.whl").write_bytes(
        fakeindex.wheel(
            {
                "acme_new/__init__.py": "def greet(name):\n    return name\n",
                "acme_new-1.0.dist-info/METADATA": (
                    "Metadata-Version: 2.1\nName: acme-new\nVersion: 1.0\n"
                ),
                "acme_new-1.0.dist-info/WHEEL": WHEEL,
                "acme_new-1.0.dist-info/RECORD": "",
            }
        )
    )
    for version, source in (("1.0", V1), ("2.0", V2)):
        (where / f"acme_kit-{version}-py3-none-any.whl").write_bytes(
            fakeindex.wheel(
                {
                    "acme_kit/__init__.py": source,
                    f"acme_kit-{version}.dist-info/METADATA": (
                        f"Metadata-Version: 2.1\nName: acme-kit\nVersion: {version}\n"
                    ),
                    f"acme_kit-{version}.dist-info/WHEEL": WHEEL,
                    f"acme_kit-{version}.dist-info/RECORD": "",
                }
            )
        )
    (where / "pytest-0-py3-none-any.whl").write_bytes(
        fakeindex.wheel(
            {
                "pytest-0.dist-info/METADATA": "Metadata-Version: 2.1\nName: pytest\nVersion: 0\n",
                "pytest-0.dist-info/WHEEL": WHEEL,
                "pytest-0.dist-info/RECORD": "",
            }
        )
    )
    return where


@pytest.fixture
def offline(links: Path, monkeypatch: pytest.MonkeyPatch) -> Mapping[str, str]:
    """uv installs from `links` alone; pytest comes from the interpreter that runs these tests."""
    monkeypatch.setenv("UV_FIND_LINKS", str(links))
    monkeypatch.setenv("UV_NO_INDEX", "1")
    monkeypatch.setenv("PYTHONPATH", sysconfig.get_paths()["purelib"])
    return dict(os.environ)


def repository(tmp_path: Path, **files: str) -> Path:
    named = {"requirements.txt": "acme-kit==1.0\n", "app.py": APP, "test_app.py": TEST}
    named.update({name.replace("__", "."): body for name, body in files.items()})
    return committed(tmp_path / "repo", named)


# The copy.


def test_the_copy_holds_what_git_lists_byte_for_byte_and_is_a_repository_of_its_own(
    tmp_path: Path,
) -> None:
    root = repository(tmp_path, run__sh="#!/bin/sh\n")
    (root / "run.sh").chmod(0o755)
    (root / ".gitignore").write_text("ignored.txt\n")
    git(root, "add", ".gitignore")
    git(root, "commit", "-qm", "ignore")
    (root / "ignored.txt").write_text("ignored")
    (root / "untracked.py").write_bytes(b"x = '\xff'\r\n")
    (root / ".obelize" / "runs").mkdir(parents=True)
    (root / ".obelize" / "runs" / "a").write_text("not copied")
    if sys.platform != "win32":
        (root / "link.py").symlink_to("/etc/hosts")
    copied = copy.make(root, tmp_path / "copy")
    made = sorted(path.name for path in (tmp_path / "copy").iterdir() if path.name != ".git")
    assert made == [
        ".gitignore",
        "app.py",
        "requirements.txt",
        "run.sh",
        "test_app.py",
        "untracked.py",
    ]
    assert (tmp_path / "copy" / "untracked.py").read_bytes() == b"x = '\xff'\r\n"
    if sys.platform != "win32":
        assert copied.left == ("link.py",)
        assert (tmp_path / "copy" / "run.sh").stat().st_mode & 0o111
    assert git(tmp_path / "copy", "status", "--porcelain").stdout == b""
    assert git(tmp_path / "copy", "log", "--format=%an").stdout == b"obelize\n"


def test_a_directory_that_is_no_repository_is_copied_by_walking_it(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("x = 1\n")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "a.pyc").write_bytes(b"\0")
    copied = copy.make(root, tmp_path / "copy")
    assert (tmp_path / "copy" / "pkg" / "a.py").read_text() == "x = 1\n"
    assert not (tmp_path / "copy" / "__pycache__").exists()
    assert copied.files == 1


def test_a_repository_past_the_limit_is_not_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(copy, "FILE_LIMIT", 2)
    with pytest.raises(copy.CopyError, match="larger than a trial copies"):
        copy.make(repository(tmp_path), tmp_path / "copy")


def test_a_file_that_vanishes_before_it_is_copied_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repository(tmp_path)
    (root / "app.py").unlink()
    assert copy.make(root, tmp_path / "copy").left == ("app.py",)


def test_the_traceback_of_each_test_that_failed_or_errored_is_kept(tmp_path: Path) -> None:
    path = junit(
        tmp_path,
        case("t::a"),
        '<testcase classname="t" name="b"><failure message="short">  the traceback  </failure>'
        "</testcase>",
        '<testcase classname="t" name="c"><error message="only a message"/></testcase>',
        case("t::d", "skipped"),
        case("t::e", "failure"),
    )
    assert tests._failures(tests._junit(path)) == {
        "t::b": "the traceback",
        "t::c": "only a message",
        "t::e": "",
    }
    assert tests._failures(None) == {}


def test_a_git_that_refuses_the_copy_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gitutil, "run", lambda *_a, **_k: None)
    with pytest.raises(copy.CopyError, match="git"):
        copy.make(repository(tmp_path), tmp_path / "copy")


# The environments.


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"pyproject.toml": "[project]\nname = 'x'\n", "uv.lock": ""}, ("lock", ())),
        ({"pyproject.toml": "[project]\nname = 'x'\n"}, ("project", ())),
        (
            {"requirements.txt": "a\n", "requirements-dev.txt": "b\n", "constraints.txt": "c\n"},
            ("requirements", ("requirements-dev.txt", "requirements.txt")),
        ),
        (
            {"pyproject.toml": "[tool.ruff]\n", "requirements.txt": "a\n"},
            ("requirements", ("requirements.txt",)),
        ),
        ({"pyproject.toml": "not toml ["}, None),
        ({}, None),
    ],
)
def test_the_dependencies_are_installed_from_the_lock_the_project_or_the_requirements(
    tmp_path: Path, files: dict[str, str], expected: tuple[str, tuple[str, ...]] | None
) -> None:
    for name, body in files.items():
        (tmp_path / name).write_text(body)
    if expected is None:
        with pytest.raises(envs.EnvError, match="no way to install"):
            envs.recipe(tmp_path)
    else:
        assert envs.recipe(tmp_path) == expected


def test_the_interpreter_a_repository_pins_is_the_one_asked_for(tmp_path: Path) -> None:
    assert envs._pinned(tmp_path) is None
    (tmp_path / ".python-version").write_text("3.12\n")
    assert envs._pinned(tmp_path) == "3.12"
    (tmp_path / ".python-version").write_text("\n")
    assert envs._pinned(tmp_path) is None


def test_without_uv_the_trial_says_where_to_get_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(envs.EnvError, match="uv is needed"):
        envs.program()


@needs_uv
def test_an_environment_has_what_the_repository_declares_and_the_release_moved_to_goes_over_it(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    work = tmp_path / "work"
    copy.make(repository(tmp_path), work)
    say: list[str] = []
    old = envs.make(work, tmp_path / "old", python=PYTHON, environ=offline, say=say.append)
    assert "acme-kit==1.0" in envs.freeze(old, work=work, environ=offline)
    assert old.python.is_file()
    assert say == ["Installing the dependencies of the repository (requirements) into old"]
    envs.install(old, "acme-kit==2.0", work=work, environ=offline)
    assert "acme-kit==2.0" in envs.freeze(old, work=work, environ=offline)


@needs_uv
def test_a_dependency_that_cannot_be_installed_is_an_error_with_what_uv_said(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    root = committed(tmp_path / "repo", {"requirements.txt": "no-such-thing==9\n"})
    work = tmp_path / "work"
    copy.make(root, work)
    with pytest.raises(envs.EnvError, match="uv pip failed"):
        envs.make(work, tmp_path / "old", python=PYTHON, environ=offline, say=print)


@needs_uv
def test_a_project_file_with_a_lock_is_synced_into_the_environment_asked_for(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    root = committed(
        tmp_path / "repo",
        {"pyproject.toml": "[project]\nname = 'x'\nversion = '1'\ndependencies = []\n"},
    )
    work = tmp_path / "work"
    copy.make(root, work)
    with pytest.raises(envs.EnvError, match="uv sync failed"):
        envs.make(work, tmp_path / "old", python="9.99", environ=offline, say=print)


# The tests, test by test.


def case(name: str, kind: str = "") -> str:
    inner = {"": "", "failure": "<failure/>", "error": "<error/>", "skipped": "<skipped/>"}[kind]
    classname, _, test = name.rpartition("::")
    return f'<testcase classname="{classname}" name="{test}">{inner}</testcase>'


def junit(tmp_path: Path, *cases: str, name: str = "j.xml") -> Path:
    path = tmp_path / name
    path.write_text(f"<testsuites><testsuite>{''.join(cases)}</testsuite></testsuites>")
    return path


def test_each_test_a_junit_file_reports_is_read_with_the_worst_of_its_outcomes(
    tmp_path: Path,
) -> None:
    path = junit(
        tmp_path,
        case("t.A::ok"),
        case("t.A::bad", "failure"),
        case("t.A::err", "error"),
        case("t.A::skip", "skipped"),
        case("t.A::twice"),
        case("t.A::twice", "failure"),
        case("t.A::thrice", "error"),
        case("t.A::thrice"),
    )
    assert tests.cases_of(path) == {
        "t.A::ok": "passed",
        "t.A::bad": "failed",
        "t.A::err": "error",
        "t.A::skip": "skipped",
        "t.A::twice": "failed",
        "t.A::thrice": "error",
    }


@pytest.mark.parametrize(
    "body",
    [
        b"not xml",
        b"<!DOCTYPE x [<!ENTITY a 'b'>]><testsuites/>",
        b"<testsuites><!ENTITY a 'b'></testsuites>",
    ],
)
def test_a_junit_file_that_is_not_xml_or_declares_an_entity_reports_nothing(
    tmp_path: Path, body: bytes
) -> None:
    path = tmp_path / "j.xml"
    path.write_bytes(body)
    assert tests.cases_of(path) == {}
    assert tests.cases_of(tmp_path / "missing.xml") == {}


def test_a_junit_file_past_the_limit_reports_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tests, "JUNIT_LIMIT", 10)
    assert tests.cases_of(junit(tmp_path, case("t::a"))) == {}


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"pytest.ini": "[pytest]\n"}, True),
        ({"tox.ini": "[pytest]\naddopts = -q\n"}, True),
        ({"setup.cfg": "[tool:pytest]\n"}, True),
        ({"pyproject.toml": "[tool.pytest.ini_options]\n"}, True),
        ({"pyproject.toml": "[tool.ruff]\n"}, False),
        ({"pyproject.toml": "not toml ["}, False),
        ({"tests/test_a.py": ""}, True),
        ({"pkg/b_test.py": ""}, True),
        ({"app.py": ""}, False),
    ],
)
def test_a_repository_is_set_up_for_pytest_by_its_configuration_or_its_tests(
    tmp_path: Path, files: dict[str, str], expected: bool
) -> None:
    for name, body in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(body)
    assert tests.configured(tmp_path) is expected


def test_the_command_is_the_persons_or_pytest_in_the_environment(tmp_path: Path) -> None:
    env = envs.Env(tmp_path / "env", "requirements")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    assert tests.argv(tmp_path, env, "make test") == ("make", "test")
    assert tests.argv(tmp_path, env, None) == (
        str(env.python),
        "-m",
        "pytest",
        "--tb=native",
        "-q",
        "--continue-on-collection-errors",
    )
    (tmp_path / "pytest.ini").unlink()
    assert tests.argv(tmp_path, env, None) is None


def phase(tmp_path: Path, **cases: str) -> tests.Phase:
    result = CommandResult(
        command="pytest", source="cli", status="pass", exit_code=0, duration_ms=1
    )
    return tests.Phase(result, dict(cases))  # type: ignore[arg-type]


def test_the_verdict_is_what_passed_before_and_does_not_pass_after(tmp_path: Path) -> None:
    before = phase(
        tmp_path, a="passed", b="passed", c="failed", d="skipped", e="passed", f="failed"
    )
    after = phase(tmp_path, a="passed", b="failed", c="passed", d="passed", f="failed")
    verdict = tests.judge(before, after, {})
    assert (verdict.status, verdict.reason, verdict.compared) == ("fail", "tests_broke", 3)
    assert verdict.broken == ("b", "e")
    assert verdict.fixed == ("c",)


def test_a_test_that_passes_the_second_time_is_flaky_and_not_a_break(tmp_path: Path) -> None:
    before = phase(tmp_path, a="passed", b="passed")
    after = phase(tmp_path, a="failed", b="error")
    verdict = tests.judge(before, after, {"a": "passed", "b": "failed"})
    assert (verdict.status, verdict.broken, verdict.flaky) == ("fail", ("b",), ("a",))
    clean = tests.judge(before, after, {"a": "passed", "b": "passed"})
    assert (clean.status, clean.reason, clean.flaky) == ("pass", None, ("a", "b"))


@pytest.mark.parametrize(
    ("before", "reason"),
    [
        (None, "no_tests"),
        ({}, "no_junit"),
        ({"a": "failed", "b": "skipped"}, "nothing_to_compare"),
    ],
)
def test_tests_that_say_nothing_before_are_no_evidence(
    tmp_path: Path, before: dict[str, str] | None, reason: str
) -> None:
    verdict = tests.judge(None if before is None else phase(tmp_path, **before), None, {})
    assert (verdict.status, verdict.reason) == ("inconclusive", reason)


def test_tests_that_ran_out_of_time_before_are_said_to_have(tmp_path: Path) -> None:
    result = CommandResult(
        command="pytest",
        source="cli",
        status="inconclusive",
        reason="timeout",
        exit_code=-15,
        duration_ms=1,
    )
    verdict = tests.judge(tests.Phase(result, {}), None, {})
    assert (verdict.status, verdict.reason) == ("inconclusive", "timeout")


def test_tests_that_run_nowhere_after_are_a_break(tmp_path: Path) -> None:
    verdict = tests.judge(phase(tmp_path, a="passed"), None, {})
    assert (verdict.status, verdict.broken) == ("fail", ("a",))


@needs_uv
def test_a_project_with_no_build_system_is_synced_into_the_environment_asked_for(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    root = committed(
        tmp_path / "repo",
        {
            "pyproject.toml": "[project]\nname = 'x'\nversion = '1'\nrequires-python = '>=3.9'\n"
            "dependencies = ['acme-kit==1.0']\n",
            ".python-version": f"{sys.version_info.major}.{sys.version_info.minor}\n",
        },
    )
    work = tmp_path / "work"
    copy.make(root, work)
    found = envs.make(work, tmp_path / "old", python=PYTHON, environ=offline, say=print)
    assert found.recipe == "project"
    assert "acme-kit==1.0" in envs.freeze(found, work=work, environ=offline)


# A trial.


def plan(
    tmp_path: Path, environ: Mapping[str, str], migrate: object, **changes: object
) -> run.Plan:
    found: dict[str, object] = {
        "root": tmp_path / "repo",
        "scratch": tmp_path / "scratch",
        "evidence": tmp_path / "evidence",
        "distribution": "acme-kit",
        "old": Version("1.0"),
        "install": "acme-kit==2.0",
        "environ": environ,
        "say": lambda _line: None,
        "migrate": migrate,
        "python": PYTHON,
    }
    return run.Plan(**{**found, **changes})  # type: ignore[arg-type]


def renamed(work: Path, _elsewhere: Collection[str] = ()) -> tuple[str, ...]:
    path = work / "app.py"
    path.write_text(path.read_text().replace("old_greet", "greet"))
    return ("app.py",)


@needs_uv
def test_a_migration_whose_tests_pass_on_the_new_release_passes_the_trial(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    repository(tmp_path)
    said: list[str] = []
    done = run.run(plan(tmp_path, offline, renamed, say=said.append))
    assert (done.verdict.status, done.verdict.compared) == ("pass", 2)
    assert done.written == ("app.py",)
    assert done.command is not None
    assert done.command[1:3] == ("-m", "pytest")
    document = json.loads((tmp_path / "evidence" / "trial.json").read_text())
    assert (document["status"], document["from"], document["to"]) == (
        "pass",
        "1.0",
        "acme-kit==2.0",
    )
    assert "acme-kit==1.0" in (tmp_path / "evidence" / "old.txt").read_text()
    assert "acme-kit==2.0" in (tmp_path / "evidence" / "new.txt").read_text()
    assert (tmp_path / "evidence" / "before" / "1.junit.xml").is_file()
    assert (tmp_path / "evidence" / "after" / "1.junit.xml").is_file()
    assert not (tmp_path / "scratch").exists()
    assert (tmp_path / "repo" / "app.py").read_text() == APP
    assert "Running the tests on acme-kit==2.0, with the migration written" in said


@needs_uv
def test_a_migration_that_leaves_tests_broken_on_the_new_release_fails_the_trial(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    repository(tmp_path)
    done = run.run(plan(tmp_path, offline, lambda _work, _e: ("app.py",)))
    assert (done.verdict.status, done.verdict.reason) == ("fail", "tests_broke")
    assert len(done.verdict.broken) == 2
    assert (tmp_path / "evidence" / "again" / "1.junit.xml").is_file()


@needs_uv
def test_a_test_that_fails_once_and_passes_again_is_flaky_and_not_a_break(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    flaky = (
        "import pathlib\nimport acme_kit\n\n\ndef test_flaky():\n"
        "    marker = pathlib.Path('flaky.marker')\n"
        "    if acme_kit.VERSION == '2.0' and not marker.exists():\n"
        "        marker.write_text('x')\n        assert False\n"
    )
    repository(tmp_path, test_flaky__py=flaky)
    done = run.run(plan(tmp_path, offline, renamed))
    assert (done.verdict.status, done.verdict.flaky) == ("pass", ("test_flaky::test_flaky",))


@needs_uv
def test_a_repository_with_no_tests_cannot_be_verified(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    committed(tmp_path / "repo", {"requirements.txt": "acme-kit==1.0\n", "app.py": APP})
    done = run.run(plan(tmp_path, offline, renamed))
    assert (done.verdict.status, done.verdict.reason, done.command) == (
        "inconclusive",
        "no_tests",
        None,
    )


@needs_uv
def test_a_migration_that_writes_nothing_leaves_nothing_to_compare(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    repository(tmp_path)
    done = run.run(plan(tmp_path, offline, lambda _work, _e: ()))
    assert (done.verdict.status, done.verdict.reason) == ("inconclusive", "nothing_to_compare")


@needs_uv
def test_the_persons_own_test_command_is_the_one_that_runs(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    repository(tmp_path)
    own = "python -m pytest -q test_app.py"
    done = run.run(plan(tmp_path, offline, renamed, test_command=own))
    assert (done.verdict.status, done.verdict.compared) == ("pass", 2)


@needs_uv
def test_a_repository_that_cannot_be_installed_ends_the_trial_and_leaves_no_copy(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    committed(tmp_path / "repo", {"app.py": APP})
    with pytest.raises(envs.EnvError, match="no way to install"):
        run.run(plan(tmp_path, offline, renamed))
    assert not (tmp_path / "scratch").exists()


def test_the_steps_uv_is_asked_for_follow_from_the_recipe_and_the_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def record(arguments: list[str], _work: Path, _environ: Mapping[str, str]) -> str:
        calls.append(arguments)
        return ""

    monkeypatch.setattr(envs, "_step", record)
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "requirements.txt").write_text("a\n")
    (flat / "setup.py").write_text("")
    envs.make(flat, tmp_path / "env", python="3.12", environ={}, say=print)
    assert [call[:2] for call in calls] == [
        ["venv", str(tmp_path / "env")],
        ["pip", "install"],
        ["pip", "install"],
        ["pip", "install"],
    ]
    assert calls[0][2:] == ["--python", "3.12"]
    assert calls[2][-2:] == ["-e", "."]
    calls.clear()
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (locked / "uv.lock").write_text("")
    envs.make(locked, tmp_path / "env2", python="3.12", environ={}, say=print)
    assert calls[0] == ["sync", "--frozen", "--python", "3.12"]
    calls.clear()
    envs.make(locked, tmp_path / "env3", python=None, environ={}, say=print)
    assert calls[0] == ["sync", "--frozen"]


@needs_uv
def test_a_move_to_another_distribution_installs_it_and_takes_the_old_one_out(
    tmp_path: Path, offline: Mapping[str, str]
) -> None:
    repository(tmp_path)

    def moved(work: Path, _elsewhere: Collection[str]) -> tuple[str, ...]:
        path = work / "app.py"
        path.write_text(
            path.read_text()
            .replace("acme_kit.old_greet", "acme_new.greet")
            .replace("import acme_kit", "import acme_new")
        )
        return ("app.py",)

    done = run.run(plan(tmp_path, offline, moved, install="acme-new==1.0", remove="acme-kit"))
    assert (done.verdict.status, done.verdict.compared) == ("pass", 2)
    frozen = (tmp_path / "evidence" / "new.txt").read_text()
    assert "acme-new==1.0" in frozen
    assert "acme-kit" not in frozen
    assert "acme-kit==1.0" in (tmp_path / "evidence" / "old.txt").read_text()


def test_a_test_that_is_gone_after_a_module_would_not_import_has_that_failure(
    tmp_path: Path,
) -> None:
    after = tests.Phase(
        phase(tmp_path).result,
        {"::test_app": "error"},
        {"::test_app": "ImportError", "pkg.test_x::test_a": "assert", "::test_x": "ImportError"},
    )
    assert after.failure("pkg.test_x::test_a") == "assert"
    assert after.failure("test_app::test_a") == "ImportError"
    assert after.failure("pkg.test_x::test_b") == "ImportError"
    assert after.failure("other::test_a") is None
