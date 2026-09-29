"""Run the ten-step protocol of docs/BENCHMARK.md over each case (deviations: ADR-042).

The default is the networked round, writing ``bench/results/round-<n>/<id>.json``;
``--fixtures-only`` is CI's offline check of ``bench/fixtures/``. Every case step goes via `shell`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ElementTree
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple, NoReturn

import cases
import yaml
from gate1_score import ACTIONABLE_KINDS, Row, compare, rows

from obelize import __version__

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "bench" / "fixtures"
RESULTS = ROOT / "bench" / "results"

# Outside this repository: pytest searches upward, so a nested checkout would use our config.
WORK = Path(tempfile.gettempdir()) / "obelize-bench"

# Named, never "whichever pack ships" (ADR-023 D8).
DEFAULT_PACK = "gemini/google-generativeai-to-google-genai"

FROM_DISTRIBUTION = "google-generativeai"
TO_DISTRIBUTION = "google-genai"

# `bench/summarize.py` refuses any other version: bump it on every shape change.
RESULT_SCHEMA_VERSION = 2

# Per-step ceilings in seconds; an overrun errors the case as `timeout`.
FETCH_TIMEOUT_S = 300
VENV_TIMEOUT_S = 300
INSTALL_TIMEOUT_S = 900
FIX_TIMEOUT_S = 900
COMPILE_TIMEOUT_S = 120
TEST_TIMEOUT_S = 600

# Characters kept per output stream; logs stay under `WORK` and are never committed.
OUTPUT_CAP = 200_000

# Written out, not derived, so adding one fails a test.
TIERS: tuple[str, ...] = (
    "verified_success",
    "patched_unverified",
    "partial",
    "unsupported",
    "wrong",
    "error",
)

# Closed: an unlisted reason is a crash, not a measurement.
ERROR_REASONS: tuple[str, ...] = (
    "fetch_failed",
    "venv_failed",
    "install_failed",
    "version_mismatch",
    "obelize_failed",
    "no_run_folder",
    "timeout",
    "work_root_not_isolated",
)

# The same four words as `obelize verify`.
TEST_STATUSES: tuple[str, ...] = ("pass", "fail", "inconclusive", "not_run")

# pytest's codes, not a shell's: 2-5 (interrupted, internal, usage, none collected) and signals
# give no verdict; `suite_status` fails a `2` whose report counts an error.
PYTEST_EXITS: Mapping[int, str] = {
    0: "pass",
    1: "fail",
    2: "inconclusive",
    3: "inconclusive",
    4: "inconclusive",
    5: "inconclusive",
}

# Configs pytest, ruff, mypy, tox and setuptools find by searching upward.
ANCESTOR_CONFIGS: frozenset[str] = frozenset(
    {
        ".pytest.ini",
        "conftest.py",
        "pyproject.toml",
        "pytest.ini",
        "setup.cfg",
        "setup.py",
        "tox.ini",
    }
)

# All else is refused, so `--fixtures-only` cannot reach the network.
FIXTURE_PROGRAMS: frozenset[str] = frozenset({sys.executable})

# The `python_build` under `--fixtures-only`, where the harness's interpreter is the case's.
HARNESS_BUILD = " ".join(sys.version.split())


class Completed(NamedTuple):
    argv: tuple[str, ...]
    exit_code: int
    duration_s: float
    timed_out: bool
    output: str


Execute = Callable[[Sequence[str], Path, Mapping[str, str], int], Completed]


class Step(NamedTuple):
    number: int
    name: str
    argv: tuple[str, ...]
    exit_code: int
    duration_s: float
    timed_out: bool


class Case(NamedTuple):
    id: str
    origin: str
    control: bool
    split: str | None
    repo: str | None
    sha: str | None
    python: str | None
    from_version: str | None
    to_version: str | None
    install: tuple[str, ...]
    test_cmd: str | None
    ground_truth: dict[str, Any]
    review: dict[str, Any]
    source: Path | None


class StepError(Exception):
    """A required step failed; `Session.error` says why."""


def shell(argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout_s: int) -> Completed:
    """Run one command, output merged; a missing program is exit 127 so the round goes on."""
    started = time.monotonic()
    try:
        finished = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as expired:
        return Completed(
            tuple(argv), 124, round(time.monotonic() - started, 3), True, _text(expired.output)
        )
    except OSError as error:
        return Completed(tuple(argv), 127, round(time.monotonic() - started, 3), False, str(error))
    return Completed(
        tuple(argv),
        finished.returncode,
        round(time.monotonic() - started, 3),
        False,
        _text(finished.stdout) + _text(finished.stderr),
    )


def offline(inner: Execute) -> Execute:
    """`inner`, refusing every program but this interpreter before it starts."""

    def execute(
        argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout_s: int
    ) -> Completed:
        if not argv or argv[0] not in FIXTURE_PROGRAMS:
            program = argv[0] if argv else "(nothing)"
            raise SystemExit(f"--fixtures-only refuses to run {program}: it may reach the network")
        return inner(argv, cwd, env, timeout_s)

    return execute


def _text(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", "replace")[:OUTPUT_CAP]


def corpus() -> list[Case]:
    data = cases.load().cases
    rounds = [_corpus_case(row, data, False) for row in data["cases"]]
    return rounds + [_corpus_case(row, data, True) for row in data["controls"]]


def _corpus_case(row: dict[str, Any], data: dict[str, Any], control: bool) -> Case:
    """One `bench/cases.yaml` row; a control's empty key makes any edit a false positive."""
    identifier = str(row.get("id") or row["full_name"].replace("/", "__"))
    truth: dict[str, Any] = row.get("ground_truth") or {
        "call_sites": [],
        "manifests": [],
        "must_not_report": [],
        "tests_cover_change": False,
    }
    return Case(
        id=identifier,
        origin="corpus",
        control=control,
        split=None if control else str(row["split"]),
        repo=str(row["repo"]),
        sha=str(row["sha"]),
        python=str(row.get("python") or cases.DEFAULT_PYTHON),
        from_version=str(row.get("from_version") or data["from_version"]),
        to_version=str(row.get("to_version") or data["to_version"]),
        install=tuple(row.get("install") or ()),
        test_cmd=row.get("test_cmd"),
        ground_truth=truth,
        review=dict(row.get("review") or {}),
        source=None,
    )


def fixtures() -> list[Case]:
    return [_fixture_case(path) for path in sorted(FIXTURES.iterdir()) if path.is_dir()]


def _fixture_case(path: Path) -> Case:
    """One `bench/fixtures/<id>/case.yaml`; a fixture pins no SDK and names no interpreter."""
    row = yaml.safe_load((path / "case.yaml").read_text(encoding="utf-8"))
    return Case(
        id=str(row["id"]),
        origin="fixture",
        control=bool(row["control"]),
        split=None,
        repo=None,
        sha=None,
        python=None,
        from_version=None,
        to_version=None,
        install=tuple(row.get("install") or ()),
        test_cmd=row.get("test_cmd"),
        ground_truth=dict(row["ground_truth"]),
        review=dict(row.get("review") or {}),
        source=path / "repo",
    )


def fetch_argv(into: Path, repo: str, sha: str) -> tuple[tuple[str, ...], ...]:
    """Fetch one commit at depth one, no history, as `bench/gate1_collect.py` does."""
    return (
        ("git", "-C", str(into), "init", "-q"),
        ("git", "-C", str(into), "remote", "add", "origin", repo),
        ("git", "-C", str(into), "fetch", "-q", "--depth", "1", "origin", sha),
        ("git", "-C", str(into), "checkout", "-q", "FETCH_HEAD"),
    )


def venv_argv(venv: Path, python: str) -> tuple[str, ...]:
    """`uv venv` on the case's full interpreter key; a bare `3.10` can resolve differently."""
    return ("uv", "venv", "--python", python, str(venv))


def pin_argv(venv_python: Path, distribution: str, version: str) -> tuple[str, ...]:
    return ("uv", "pip", "install", "--python", str(venv_python), f"{distribution}=={version}")


def probe_argv(venv_python: Path, distribution: str) -> tuple[str, ...]:
    """Ask the venv's own interpreter, not `uv pip show`, which version it imports."""
    program = "import importlib.metadata as m,sys;print(m.version(sys.argv[1]))\n"
    return (str(venv_python), "-c", program, distribution)


def compile_argv(venv_python: Path, paths: Sequence[str]) -> tuple[str, ...]:
    """Compile in the case interpreter; `compile()` writes no bytecode beside the source."""
    program = "import sys\nfor p in sys.argv[1:]:\n    compile(open(p,'rb').read(), p, 'exec')\n"
    return (str(venv_python), "-c", program, *paths)


def fix_argv(checkout: Path) -> tuple[str, ...]:
    """Step 6. No `--verify`: the SDK swap is step 7, so obelize's own check would fail every case.

    `--model none`: the round measures the rules, never the maintainer's configured model and key.
    """
    return (
        sys.executable,
        "-m",
        "obelize.cli",
        "fix",
        "--repo",
        str(checkout),
        "--pack",
        DEFAULT_PACK,
        "--apply",
        "--non-interactive",
        "--model",
        "none",
        "--json",
    )


PYTHON_NAMES: frozenset[str] = frozenset({"python", "python3"})


def suite_argv(command: str, junit: Path | None, interpreter: Path) -> tuple[str, ...]:
    """Split a reviewed command with `shlex`, never a shell, and add junit as `obelize verify` does.

    A leading `python` becomes the case interpreter, not `PATH`'s.
    """
    argv = tuple(shlex.split(command))
    if argv and argv[0] in PYTHON_NAMES:
        argv = (str(interpreter), *argv[1:])
    extra = () if junit is None or not _is_pytest(argv) else (f"--junitxml={junit}",)
    return argv + extra


def _is_pytest(argv: Sequence[str]) -> bool:
    """Whether this is pytest without a `--junitxml` of its own."""
    if any(argument.startswith("--junitxml") for argument in argv):
        return False
    return _pytest_command(argv)


def _pytest_command(argv: Sequence[str]) -> bool:
    """Whether this is pytest at all; `suite_status` asks it of the argv that ran."""
    head = list(argv[:3])
    return head[:1] == ["pytest"] or head[1:3] == ["-m", "pytest"]


def elide(
    argv: Sequence[str], checkout: Path | None = None, logs: Path | None = None
) -> tuple[str, ...]:
    """Replace each absolute path this harness chose with a placeholder: results are public."""
    pairs: list[tuple[str, str]] = []
    for path, name in (
        (Path(sys.executable), "<harness-python>"),
        (logs, "<logs>"),
        (checkout, "<case>"),
        (WORK, "<work>"),
        (ROOT, "<repo>"),
    ):
        if path is None:
            continue
        # Both spellings: on macOS `/var` is a symlink to `/private/var`.
        pairs += [(form, name) for form in dict.fromkeys((str(path), str(path.resolve())))]
    out: list[str] = []
    for argument in argv:
        for absolute, name in pairs:
            argument = argument.replace(absolute, name)
        out.append(argument)
    return tuple(out)


def unisolated(checkout: Path) -> list[str]:
    """Tool configurations strictly above a checkout, nearest first (ADR-043 D1)."""
    found: list[str] = []
    for level, parent in enumerate(checkout.resolve().parents, start=1):
        found += [
            f"{name} ({level} level(s) up)"
            for name in sorted(ANCESTOR_CONFIGS)
            if (parent / name).is_file()
        ]
    return found


def observed_version(completed: Completed) -> str | None:
    if completed.exit_code != 0:
        return None
    lines = [line.strip() for line in completed.output.splitlines() if line.strip()]
    return lines[-1] if lines else None


def mismatch(distribution: str, wanted: str, observed: str | None) -> str | None:
    """Why this install is not the pin, or `None`; `0.8.6` is not `0.8.6.post1`.

    A resolver can exit 0 after backtracking to another release, so every pin is read back.
    """
    if observed is None:
        return f"{distribution}: the case venv could not be asked what it installed"
    if observed != wanted:
        return f"{distribution}: pinned {wanted}, installed {observed}"
    return None


def suite_status(completed: Completed | None, failed: int | None = None) -> str:
    """A phase's status in `obelize verify`'s words; pytest's exit codes via `PYTEST_EXITS`.

    `failed` is the report's failures plus errors: exit `2` with one is an unimportable test module.
    """
    if completed is None:
        return "not_run"
    if completed.timed_out:
        return "inconclusive"
    if _pytest_command(completed.argv):
        if completed.exit_code == 2 and failed:
            return "fail"
        return PYTEST_EXITS.get(completed.exit_code, "inconclusive")
    return "pass" if completed.exit_code == 0 else "fail"


def junit_counts(path: Path) -> tuple[int | None, int | None, int | None]:
    """`(passed, failed, skipped)` from a junit report; nulls, not zeros, when there is none."""
    try:
        tree = ElementTree.parse(path)  # noqa: S314 - our own report, not untrusted input
    except (OSError, ElementTree.ParseError):
        return (None, None, None)
    total = failed = skipped = 0
    for suite in tree.iter("testsuite"):
        total += int(suite.get("tests", "0"))
        failed += int(suite.get("failures", "0")) + int(suite.get("errors", "0"))
        skipped += int(suite.get("skipped", "0"))
    return (total - failed - skipped, failed, skipped)


def key_rows(case: Case) -> Counter[Row]:
    """The key's `ACTIONABLE_KINDS` call sites, the multiset precision is computed over."""
    return Counter(
        Row(
            path=str(row["path"]),
            line=int(row["line"]),
            kind=str(row["kind"]),
            symbol=str(row["symbol"]),
        )
        for row in case.ground_truth.get("call_sites") or ()
        if row["kind"] in ACTIONABLE_KINDS
    )


def expected_rows(case: Case) -> list[tuple[str, int, str]]:
    """Every key row to change as `(path, line, symbol)`, `dynamic` rows (mock targets) included.

    The symbol matters: one `requirements.txt` line can hold two rows, one applied, one withheld.
    """
    both: Iterable[dict[str, Any]] = [
        *(case.ground_truth.get("call_sites") or ()),
        *(case.ground_truth.get("manifests") or ()),
    ]
    return [(str(row["path"]), int(row["line"]), str(row["symbol"])) for row in both]


def applied_positions(plan: dict[str, Any], written: Iterable[str]) -> Counter[tuple[str, int]]:
    """Where auto edits landed: planned *and* in a file `file_edits` says was written."""
    files = set(written)
    return Counter(
        (str(edit["path"]), int(edit["line"]))
        for edit in plan.get("edits") or ()
        if edit.get("status") == "auto" and edit["path"] in files
    )


def withheld_rows(run: dict[str, Any]) -> set[tuple[str, int, str]]:
    """Rows `run.json` says the run refused, keyed like the ground truth."""
    return {
        (str(row["path"]), int(row["line"]), str(row["symbol"] or ""))
        for row in run.get("withheld") or ()
    }


def unmigrated(case: Case, plan: dict[str, Any], run: dict[str, Any]) -> int:
    """Key rows the run refused, or never reported (no applied edit landed on the line)."""
    refused = withheld_rows(run)
    landed = applied_positions(plan, [edit["path"] for edit in run.get("file_edits") or ()])
    return sum(
        1
        for path, line, symbol in expected_rows(case)
        if (path, line, symbol) in refused or not landed[(path, line)]
    )


def measure(
    case: Case, findings: list[dict[str, Any]], plan: dict[str, Any], run: dict[str, Any]
) -> dict[str, Any]:
    """`docs/BENCHMARK.md`'s measurement table, from one run folder."""
    written = [edit["path"] for edit in run.get("file_edits") or ()]
    landed = applied_positions(plan, written)
    wanted = Counter((path, line) for path, line, _ in expected_rows(case))
    accuracy = compare(key_rows(case), rows(findings, ACTIONABLE_KINDS))
    return {
        "detected": accuracy.true_positive + accuracy.false_positive,
        "false_positive": accuracy.false_positive,
        "missed_call_site": accuracy.missed,
        "unmigrated": unmigrated(case, plan, run),
        "patch_applied": bool(written),
        "false_positive_edit": sum((landed - wanted).values()),
    }


def tier(record: Mapping[str, Any]) -> str:
    """The record's tier by precedence, never assigned.

    A broken repository is `wrong`, never `partial`; writing nothing is a refusal, `unsupported`.
    """
    if record["error"] is not None:
        return "error"
    measured = record["measurements"]
    if _is_wrong(measured):
        return "wrong"
    if not measured["patch_applied"]:
        return "unsupported"
    if measured["unmigrated"] > 0:
        return "partial"
    if _is_verified(measured):
        return "verified_success"
    return "patched_unverified"


def _is_wrong(measured: Mapping[str, Any]) -> bool:
    """A wrong, uncompiling or false-positive edit, or a test regression over a patch.

    Without a patch, a failing after-run measures the SDK swap, not the tool.
    """
    regressed = (
        measured["patch_applied"]
        and measured["tests_baseline"]["status"] == "pass"
        and measured["tests_after"]["status"] == "fail"
    )
    return bool(
        measured["patch_correct"] is False
        or measured["patch_compiles"] is False
        or measured["false_positive_edit"] > 0
        or regressed
    )


def _is_verified(measured: Mapping[str, Any]) -> bool:
    """Everything `verified_success` asks; an unreviewed (null) `human_edits` is not zero."""
    return bool(
        measured["false_positive"] == 0
        and measured["missed_call_site"] == 0
        and measured["human_edits"] == 0
        and measured["tests_baseline"]["status"] == "pass"
        and measured["tests_after"]["status"] == "pass"
        and _ran_something(measured["tests_after"])
        and measured["tests_cover_change"]
    )


def _ran_something(phase: Mapping[str, Any]) -> bool:
    """Whether the after-run ran a test (skip-everything exits 0); no junit report counts as yes.

    Not sufficient: the covering test is still the key's `tests_cover_change` (COVERAGE.md gap 27).
    """
    return phase["passed"] is None or phase["passed"] > 0


def ceiling(case: Case) -> str | None:
    """Why the key alone caps this case below `verified_success`, or `None`."""
    truth = case.ground_truth
    rowset: list[dict[str, Any]] = [
        *(truth.get("call_sites") or ()),
        *(truth.get("manifests") or ()),
    ]
    if case.control:
        return "a negative control is excluded from the rate"
    if not rowset:
        return "the key names nothing to migrate"
    if case.test_cmd is None:
        return "no test command"
    if not truth.get("tests_cover_change"):
        return "the tests do not cover the change"
    if any(row["label"] != "auto" for row in rowset):
        return "a row the key marks `manual`"
    if any(row.get("kind") == "dynamic" for row in rowset):
        return "a row the pack flags rather than edits"
    return None


@dataclass
class Session:
    case: Case
    execute: Execute
    checkout: Path
    logs: Path
    environ: dict[str, str]
    steps: list[Step] = field(default_factory=list)
    error: dict[str, Any] | None = None

    def do(
        self,
        number: int,
        name: str,
        argv: Sequence[str],
        *,
        timeout_s: int,
        reason: str | None,
    ) -> Completed:
        """Run and record a step; with a `reason`, a failure or timeout errors the case."""
        completed = self.execute(argv, self.checkout, self.environ, timeout_s)
        self.steps.append(
            Step(
                number,
                name,
                elide(completed.argv, self.checkout, self.logs),
                completed.exit_code,
                completed.duration_s,
                completed.timed_out,
            )
        )
        self._log(name, completed)
        if reason is None:
            return completed
        if completed.timed_out:
            self.fail(name, "timeout", f"{name} outlasted {timeout_s}s")
        if completed.exit_code != 0:
            self.fail(name, reason, f"{name} exited {completed.exit_code}")
        return completed

    def fail(self, step: str, reason: str, detail: str) -> NoReturn:
        self.error = {"step": step, "reason": reason, "detail": detail}
        raise StepError(detail)

    def _log(self, name: str, completed: Completed) -> None:
        """Write the output to the log, never anywhere published."""
        self.logs.mkdir(parents=True, exist_ok=True)
        (self.logs / f"{len(self.steps):02d}-{name}.log").write_text(
            f"$ {shlex.join(completed.argv)}\n\n{completed.output}", encoding="utf-8"
        )


def run_case(case: Case, *, execute: Execute, fixtures_only: bool) -> dict[str, Any]:
    """The ten steps, in order, over one case."""
    checkout = WORK / ("fixtures" if fixtures_only else _round_name()) / case.id
    shutil.rmtree(checkout, ignore_errors=True)
    logs = checkout.parent / f"{case.id}.logs"
    shutil.rmtree(logs, ignore_errors=True)
    session = Session(case, execute, checkout, logs, dict(os.environ))

    interpreter = Path(sys.executable)
    build: str | None = HARNESS_BUILD
    baseline: Completed | None = None
    after: Completed | None = None
    findings: list[dict[str, Any]] = []
    plan: dict[str, Any] = {}
    run: dict[str, Any] = {}
    compiles: bool | None = None
    observed: dict[str, str | None] = {"sdk_from": None, "sdk_to": None}
    junit = logs / "junit"
    runtime = 0.0

    try:
        _isolated(session, checkout)
        if fixtures_only:
            _materialise(case, checkout)
        else:
            interpreter, build = _prepare(session, case, checkout)
            observed["sdk_from"] = _install_pin(
                session, 4, "install-from", interpreter, FROM_DISTRIBUTION, case.from_version
            )
        baseline = _phase(session, 5, "baseline", case, junit, interpreter)
        runtime, findings, plan, run = _fix(session, checkout)
        compiles = _compile(session, interpreter, run)
        if not fixtures_only:
            observed["sdk_to"] = _install_pin(
                session, 7, "install-to", interpreter, TO_DISTRIBUTION, case.to_version
            )
        after = _phase(session, 8, "after", case, junit, interpreter)
    except StepError:
        pass

    measured = measure(case, findings, plan, run) if session.error is None else _unmeasured()
    measured.update(
        {
            "patch_compiles": compiles,
            "tests_baseline": _phase_result(baseline, junit, "baseline"),
            "tests_after": _phase_result(after, junit, "after"),
            "tests_cover_change": bool(case.ground_truth.get("tests_cover_change")),
            "human_edits": case.review.get("human_edits"),
            "patch_correct": case.review.get("patch_correct"),
            "pr_opened": None,
            "pr_merged": None,
            "runtime_seconds": round(runtime, 3),
            "llm_tokens_in": 0,
            "llm_tokens_out": 0,
            "llm_cost_usd": 0.0,
        }
    )
    record: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "case": case.id,
        "origin": case.origin,
        "control": case.control,
        "split": case.split,
        "error": session.error,
        "measurements": measured,
        "steps": [step._asdict() for step in session.steps],
        "provenance": provenance(case, interpreter, build, observed),
    }
    record["tier"] = tier(record)
    return record


def _isolated(session: Session, checkout: Path) -> None:
    """Before the fetch, error a case whose checkout sits inside another project."""
    found = unisolated(checkout)
    if found:
        session.fail("isolation", "work_root_not_isolated", "; ".join(found))


def _unmeasured() -> dict[str, Any]:
    return {
        "detected": 0,
        "false_positive": 0,
        "missed_call_site": 0,
        "unmigrated": 0,
        "patch_applied": False,
        "false_positive_edit": 0,
    }


def _round_name() -> str:
    """`round-<n>` from `bench/cases.yaml`, never a flag: two corpora must not share a folder."""
    return f"round-{cases.load().cases['round']}"


def _materialise(case: Case, checkout: Path) -> None:
    """Copy a fixture out: `fix --apply` in place would rewrite it and leave a run folder."""
    assert case.source is not None  # noqa: S101 - a fixture always has one
    shutil.copytree(case.source, checkout)


def _prepare(session: Session, case: Case, checkout: Path) -> tuple[Path, str | None]:
    """Steps 1 to 3: fetch, venv, install."""
    checkout.mkdir(parents=True)
    assert case.repo is not None  # noqa: S101 - a corpus case always has all three
    assert case.sha is not None  # noqa: S101
    assert case.python is not None  # noqa: S101
    for argv in fetch_argv(checkout, case.repo, case.sha):
        session.do(1, "fetch", argv, timeout_s=FETCH_TIMEOUT_S, reason="fetch_failed")
    venv = checkout / ".venv"
    session.do(
        2, "venv", venv_argv(venv, case.python), timeout_s=VENV_TIMEOUT_S, reason="venv_failed"
    )
    interpreter, build = _resolved(session, venv)
    session.environ.update(
        {
            "VIRTUAL_ENV": str(venv),
            "PATH": f"{venv / 'bin'}{os.pathsep}{session.environ.get('PATH', '')}",
        }
    )
    for command in case.install:
        session.do(
            3, "install", shlex.split(command), timeout_s=INSTALL_TIMEOUT_S, reason="install_failed"
        )
    return interpreter, build


def _resolved(session: Session, venv: Path) -> tuple[Path, str | None]:
    """The venv interpreter's path and `sys.version`; the path alone is the same for every case."""
    program = "import sys;print(sys.executable);print(' '.join(sys.version.split()))"
    probe = (str(venv / "bin" / "python"), "-c", program)
    completed = session.do(2, "resolve", probe, timeout_s=VENV_TIMEOUT_S, reason="venv_failed")
    lines = [line.strip() for line in completed.output.splitlines() if line.strip()]
    if len(lines) < 2:
        return venv / "bin" / "python", None
    return Path(lines[-2]), lines[-1]


def _install_pin(
    session: Session,
    number: int,
    name: str,
    interpreter: Path,
    distribution: str,
    version: str | None,
) -> str | None:
    """Install one pin and read it back; a mismatch errors the case."""
    assert version is not None  # noqa: S101 - a corpus case always pins both
    session.do(
        number,
        name,
        pin_argv(interpreter, distribution, version),
        timeout_s=INSTALL_TIMEOUT_S,
        reason="install_failed",
    )
    probe = session.do(
        number,
        f"{name}-check",
        probe_argv(interpreter, distribution),
        timeout_s=VENV_TIMEOUT_S,
        reason=None,
    )
    seen = observed_version(probe)
    wrong = mismatch(distribution, version, seen)
    if wrong is not None:
        session.fail(f"{name}-check", "version_mismatch", wrong)
    return seen


def _phase(
    session: Session, number: int, name: str, case: Case, junit: Path, interpreter: Path
) -> Completed | None:
    """A test run; its exit code is a measurement, never a failure."""
    if case.test_cmd is None:
        return None
    report = junit / f"{name}.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    return session.do(
        number,
        name,
        suite_argv(case.test_cmd, report, interpreter),
        timeout_s=TEST_TIMEOUT_S,
        reason=None,
    )


def _phase_result(completed: Completed | None, junit: Path, name: str) -> dict[str, Any]:
    """`{status, passed, failed, skipped}`; `skipped` shows a green suite that ran nothing."""
    passed, failed, skipped = junit_counts(junit / f"{name}.xml")
    return {
        "status": suite_status(completed, failed),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }


def _fix(
    session: Session, checkout: Path
) -> tuple[float, list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Step 6, then its run folder."""
    completed = session.do(6, "fix", fix_argv(checkout), timeout_s=FIX_TIMEOUT_S, reason=None)
    if completed.timed_out:
        session.fail("fix", "timeout", f"obelize fix outlasted {FIX_TIMEOUT_S}s")
    if completed.exit_code not in (0, 4, 6):
        session.fail("fix", "obelize_failed", f"obelize fix exited {completed.exit_code}")
    pointer = checkout / ".obelize" / "latest"
    if not pointer.is_file():
        session.fail("fix", "no_run_folder", "obelize wrote no run folder")
    folder = checkout / ".obelize" / "runs" / pointer.read_text(encoding="utf-8").strip()
    return (
        completed.duration_s,
        list(_read(folder / "findings.json").get("findings") or ()),
        _read(folder / "plan.json"),
        _read(folder / "run.json"),
    )


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _compile(session: Session, interpreter: Path, run: dict[str, Any]) -> bool | None:
    """The compile gate obelize skips without a verify command (ADR-042 D2).

    `None` when nothing was written: `False` would grade a correct refusal `wrong`.
    """
    paths = [
        edit["path"] for edit in run.get("file_edits") or () if str(edit["path"]).endswith(".py")
    ]
    if not paths:
        return None
    completed = session.do(
        6, "compile", compile_argv(interpreter, paths), timeout_s=COMPILE_TIMEOUT_S, reason=None
    )
    return completed.exit_code == 0


def provenance(
    case: Case, interpreter: Path, build: str | None, observed: Mapping[str, str | None]
) -> dict[str, Any]:
    from obelize.packs import loader

    loaded = loader.load(DEFAULT_PACK)
    return {
        "obelize_version": __version__,
        "obelize_commit": _commit(),
        "pack": DEFAULT_PACK,
        "pack_sha256": loaded.sha256,
        "spec_sha256": loader.spec_digest(loader.to_scan_spec(loaded)),
        "python": case.python,
        "python_executable": elide((str(interpreter),))[0],
        "python_build": build,
        "machine": platform.machine(),
        "os": platform.system(),
        "sdk_from": observed.get("sdk_from"),
        "sdk_to": observed.get("sdk_to"),
        "run_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _commit() -> str | None:
    """`HEAD` of this repository, or `None` outside a checkout (recorded, not fatal)."""
    finished = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, check=False
    )
    if finished.returncode != 0:
        return None
    return finished.stdout.decode().strip()


def comparable(record: Mapping[str, Any]) -> dict[str, Any]:
    """The part of a result two runs must agree on: nothing a wall clock touches."""
    measured = {
        key: value
        for key, value in record["measurements"].items()
        if key not in {"runtime_seconds", "tests_cover_change"}
    }
    return {
        "tier": record["tier"],
        "error": record["error"],
        "measurements": measured,
        "steps": [[step["name"], step["exit_code"]] for step in record["steps"]],
    }


def expected(case: Case) -> dict[str, Any]:
    """The fixture's `expected.json`, in `comparable`'s shape."""
    assert case.source is not None  # noqa: S101
    loaded: dict[str, Any] = json.loads(
        (case.source.parent / "expected.json").read_text(encoding="utf-8")
    )
    loaded["steps"] = [list(step) for step in loaded["steps"]]
    return loaded


def differences(got: Mapping[str, Any], want: Mapping[str, Any]) -> list[str]:
    """Name every key the two disagree on; a nested diff is unreadable in a CI log."""
    out: list[str] = []
    for key in ("tier", "error", "steps"):
        if got[key] != want[key]:
            out.append(f"{key}: {got[key]!r} != {want[key]!r}")
    for key in sorted(set(got["measurements"]) | set(want["measurements"])):
        mine, theirs = got["measurements"].get(key), want["measurements"].get(key)
        if mine != theirs:
            out.append(f"measurements.{key}: {mine!r} != {theirs!r}")
    return out


def fixtures_pass(execute: Execute) -> int:
    failures = 0
    for case in fixtures():
        record = run_case(case, execute=execute, fixtures_only=True)
        wrong = differences(comparable(record), expected(case))
        for line in wrong:
            print(f"{case.id}: {line}", flush=True)
        failures += bool(wrong)
        print(f"{case.id}: {record['tier']}{' (MISMATCH)' if wrong else ''}", flush=True)
    print(f"{len(fixtures())} fixture(s), {failures} mismatch(es)", flush=True)
    return 1 if failures else 0


def round_pass(only: str | None) -> int:
    into = RESULTS / _round_name()
    into.mkdir(parents=True, exist_ok=True)
    selected = [case for case in corpus() if only is None or case.id == only]
    if not selected:
        print(f"no case named {only}", flush=True)
        return 1
    for case in selected:
        record = run_case(case, execute=shell, fixtures_only=False)
        destination = into / f"{case.id}.json"
        destination.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"{case.id}: {record['tier']} -> {destination}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the benchmark protocol.")
    parser.add_argument(
        "--fixtures-only",
        action="store_true",
        help="run the offline fixtures and compare them against their expected results",
    )
    parser.add_argument("--case", help="run one case of the round by id")
    arguments = parser.parse_args(argv)
    if arguments.fixtures_only:
        if arguments.case is not None:
            print("--case and --fixtures-only are different runs", flush=True)
            return 2
        return fixtures_pass(offline(shell))
    return round_pass(arguments.case)


if __name__ == "__main__":  # pragma: no cover - the module is imported by its test
    sys.exit(main())
