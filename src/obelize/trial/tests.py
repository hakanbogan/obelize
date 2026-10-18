"""The repository's own tests, run in an environment and compared test by test.

A test is its junit `classname::name`. What the migration broke is a test that passed before and
does not pass after, or is not there after (a module that no longer imports takes its tests with
it). A test that failed before is no evidence either way.
"""

from __future__ import annotations

import os
import shlex
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from obelize.verify import runner as verifier

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from obelize.models import CommandResult
    from obelize.trial.envs import Env

Outcome = Literal["passed", "failed", "error", "skipped"]
Status = Literal["pass", "fail", "inconclusive"]
Reason = Literal["no_tests", "no_junit", "nothing_to_compare", "tests_broke"]
JUNIT_LIMIT: Final = 64 << 20
_WORSE: Final = {"passed": 0, "skipped": 1, "failed": 2, "error": 3}


@dataclass(frozen=True, slots=True)
class Phase:
    """One run of the tests: what the command did, and each test it reported."""

    result: CommandResult
    cases: Mapping[str, Outcome]


@dataclass(frozen=True, slots=True)
class Verdict:
    status: Status
    reason: Reason | None
    compared: int
    broken: tuple[str, ...]
    fixed: tuple[str, ...]
    flaky: tuple[str, ...] = ()


def configured(work: Path) -> bool:
    """Whether the repository is set up for pytest: its configuration, or tests where it looks."""
    if (work / "pytest.ini").is_file():
        return True
    if "[pytest]" in _text(work / "tox.ini") or "[tool:pytest]" in _text(work / "setup.cfg"):
        return True
    try:
        pyproject = tomllib.loads(_text(work / "pyproject.toml"))
    except ValueError:
        pyproject = {}
    if "pytest" in pyproject.get("tool", {}):
        return True
    return any(work.glob("**/test_*.py")) or any(work.glob("**/*_test.py"))


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def argv(work: Path, env: Env, custom: str | None) -> tuple[str, ...] | None:
    """The tests as a command: the person's, else pytest where the repository is set up for it."""
    if custom:
        return tuple(shlex.split(custom))
    return (str(env.python), "-m", "pytest", "--tb=native", "-q") if configured(work) else None


def run(
    work: Path,
    env: Env,
    command: tuple[str, ...],
    folder: Path,
    *,
    timeout_s: int,
    environ: Mapping[str, str],
    index: int,
) -> Phase:
    """The command in `work` with the environment first on PATH; its junit is kept in `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    inside = {
        **environ,
        "PATH": f"{env.bin}{os.pathsep}{environ.get('PATH', '')}",
        "VIRTUAL_ENV": str(env.path),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    done = verifier.execute(
        work,
        verifier.Command(" ".join(shlex.quote(word) for word in command), "cli", command),
        timeout_s=timeout_s,
        environ=inside,
        junit_dir=folder,
        index=index,
    )
    (folder / f"{index}.output.txt").write_text(
        f"{done.command}\nexit {done.exit_code}, {done.status}\n\n{done.output}", encoding="utf-8"
    )
    cases = cases_of(folder / done.junit) if done.junit else {}
    return Phase(done, cases)


def cases_of(path: Path) -> dict[str, Outcome]:
    """Each test a junit file reports and how it ended; an unreadable or hostile file, none."""
    try:
        with path.open("rb") as handle:
            data = handle.read(JUNIT_LIMIT + 1)
    except OSError:
        return {}
    if len(data) > JUNIT_LIMIT or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return {}
    try:
        root = ET.fromstring(data)  # noqa: S314 - no DOCTYPE or ENTITY, so no expansion
    except ET.ParseError:
        return {}
    found: dict[str, Outcome] = {}
    for case in root.iter("testcase"):
        name = f"{case.get('classname', '')}::{case.get('name', '')}"
        ended = _ended(case)
        if name not in found or _WORSE[ended] > _WORSE[found[name]]:
            found[name] = ended
    return found


def _ended(case: ET.Element) -> Outcome:
    if case.find("error") is not None:
        return "error"
    if case.find("failure") is not None:
        return "failed"
    return "skipped" if case.find("skipped") is not None else "passed"


def judge(before: Phase | None, after: Phase | None, rerun: Mapping[str, Outcome]) -> Verdict:
    """What the tests say of the migration; `rerun` is the second run of what broke."""
    if before is None:
        return Verdict("inconclusive", "no_tests", 0, (), ())
    if not before.cases:
        return Verdict("inconclusive", "no_junit", 0, (), ())
    passed = sorted(name for name, ended in before.cases.items() if ended == "passed")
    if not passed:
        return Verdict("inconclusive", "nothing_to_compare", 0, (), ())
    now = after.cases if after is not None else {}
    broken = tuple(name for name in passed if now.get(name, "error") in ("failed", "error"))
    flaky = tuple(name for name in broken if rerun.get(name) == "passed")
    broken = tuple(name for name in broken if name not in flaky)
    fixed = tuple(
        sorted(
            name
            for name, ended in before.cases.items()
            if ended in ("failed", "error") and now.get(name) == "passed"
        )
    )
    reason: Reason | None = "tests_broke" if broken else None
    return Verdict("fail" if broken else "pass", reason, len(passed), broken, fixed, flaky)
