"""A trial, from the copy to the verdict: tests before, the migration, tests after.

Everything is done in a copy and in environments outside the repository; the repository is read
once, to make the copy. The evidence of the trial (the junit files, what was installed, the
verdict) goes to a folder the caller names, which the caller removes the copy and environments
around.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from obelize.trial import copy, envs, tests

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from packaging.version import Version

TEST_TIMEOUT_S: Final = 1800


@dataclass(frozen=True, slots=True)
class Plan:
    """Every decision taken; the CLI reads the terminal and the environment."""

    root: Path
    # Where the copy and the environments are made; it must not exist.
    scratch: Path
    # Where the evidence goes; it must not exist.
    evidence: Path
    distribution: str
    old: Version
    # The requirement installed for the release moved to, and the distribution it replaces.
    install: str
    environ: Mapping[str, str]
    say: Callable[[str], None]
    # Writes the migration into a tree, and returns the paths it wrote.
    migrate: Callable[[Path], Sequence[str]]
    remove: str | None = None
    python: str | None = None
    test_command: str | None = None
    timeout_s: int = TEST_TIMEOUT_S


@dataclass(frozen=True, slots=True)
class Trial:
    verdict: tests.Verdict
    written: tuple[str, ...]
    command: tuple[str, ...] | None
    evidence: Path
    # What the migration wrote, by path: the bytes a branch is made of.
    changes: Mapping[str, bytes]


def run(plan: Plan) -> Trial:
    """Make the copy and the environments, run the tests, write the migration, run them again.

    Raises `copy.CopyError` or `envs.EnvError`; a migration that wrote nothing is a verdict of
    `inconclusive` without a second run. The copy and the environments are removed.
    """
    plan.evidence.mkdir(mode=0o700, parents=True)
    try:
        work = plan.scratch / "work"
        plan.say(f"Copying the repository into {plan.scratch.name}")
        copy.make(plan.root, work)
        old = envs.make(
            work,
            plan.scratch / "old",
            python=plan.python,
            environ=plan.environ,
            say=plan.say,
        )
        (plan.evidence / "old.txt").write_text(
            envs.freeze(old, work=work, environ=plan.environ), encoding="utf-8"
        )
        new = envs.make(
            work,
            plan.scratch / "new",
            python=plan.python,
            environ=plan.environ,
            say=plan.say,
        )
        plan.say(f"Installing {plan.install} over it")
        envs.install(new, plan.install, work=work, environ=plan.environ)
        if plan.remove:
            envs.uninstall(new, plan.remove, work=work, environ=plan.environ)
        (plan.evidence / "new.txt").write_text(
            envs.freeze(new, work=work, environ=plan.environ), encoding="utf-8"
        )
        return _judged(plan, work, old, new)
    finally:
        shutil.rmtree(plan.scratch, ignore_errors=True)


def _judged(plan: Plan, work: Path, old: envs.Env, new: envs.Env) -> Trial:
    command = tests.argv(work, old, plan.test_command)
    if command is None:
        return _done(plan, tests.judge(None, None, {}), (), None)
    # The same tests, run by each environment's own interpreter.
    later = tests.argv(work, new, plan.test_command) or command
    plan.say("Running the tests on the release in use")
    before = tests.run(
        work,
        old,
        command,
        plan.evidence / "before",
        timeout_s=plan.timeout_s,
        environ=plan.environ,
        index=1,
    )
    written = tuple(plan.migrate(work))
    if not written:
        return _done(
            plan, tests.Verdict("inconclusive", "nothing_to_compare", 0, (), ()), (), command
        )
    plan.say(f"Running the tests on {plan.install}, with the migration written")
    after = tests.run(
        work,
        new,
        later,
        plan.evidence / "after",
        timeout_s=plan.timeout_s,
        environ=plan.environ,
        index=1,
    )
    again: Mapping[str, tests.Outcome] = {}
    first = tests.judge(before, after, {})
    if first.broken:
        plan.say(f"Running the {len(first.broken)} test(s) that broke once more")
        again = tests.run(
            work,
            new,
            (*later, "--lf"),
            plan.evidence / "again",
            timeout_s=plan.timeout_s,
            environ=plan.environ,
            index=1,
        ).cases
    return _done(plan, tests.judge(before, after, again), written, command, work)


def _done(
    plan: Plan,
    verdict: tests.Verdict,
    written: tuple[str, ...],
    command: tuple[str, ...] | None,
    work: Path | None = None,
) -> Trial:
    document = {
        "distribution": plan.distribution,
        "from": str(plan.old),
        "to": plan.install,
        "command": list(command) if command else None,
        "status": verdict.status,
        "reason": verdict.reason,
        "compared": verdict.compared,
        "broken": list(verdict.broken),
        "fixed": list(verdict.fixed),
        "flaky": list(verdict.flaky),
        "written": list(written),
    }
    (plan.evidence / "trial.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    kept = {path: (work / path).read_bytes() for path in written} if work is not None else {}
    return Trial(verdict, written, command, plan.evidence, kept)
