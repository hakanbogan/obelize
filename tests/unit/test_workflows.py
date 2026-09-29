"""What the workflows run, on which events, what a release checks before it uploads, and that a
Windows run reports all it can.

Each `if:` is evaluated, not matched as text; an unknown expression shape fails the test. The
release steps that decide something run here under bash, with `gh` and `uv` stubbed.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import textwrap
import tomllib
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

EQUALS = re.compile(r"^([a-z_.]+) == '([^']*)'$")
STARTS_WITH = re.compile(r"^startsWith\(([a-z_.]+), '([^']*)'\)$")


def _atom(atom: str, context: dict[str, str]) -> bool:
    if match := EQUALS.match(atom):
        return context[match.group(1)] == match.group(2)
    if match := STARTS_WITH.match(atom):
        return context[match.group(1)].startswith(match.group(2))
    raise ValueError(f"no rule for the guard atom {atom!r}; extend _holds")


def _holds(expression: str, context: dict[str, str]) -> bool:
    """Evaluate an `||` of `&&` chains of EQUALS and STARTS_WITH atoms, the shapes guards use.

    Every atom is evaluated, so an unknown one fails even where the answer is already known.
    """
    terms = [
        [_atom(atom.strip(), context) for atom in term.split("&&")]
        for term in expression.split("||")
    ]
    return any(all(term) for term in terms)


def _event(visibility: str, name: str, ref: str) -> dict[str, str]:
    return {
        "github.event.repository.visibility": visibility,
        "github.event_name": name,
        "github.ref": ref,
        "github.ref_type": "tag" if ref.startswith("refs/tags/") else "branch",
    }


# Every event but a schedule that a workflow here triggers on. Private pushes and pull requests
# spend the paid quota; ADR-004 keeps manual runs and release tags.
EVENTS = [
    ("private push to main", _event("private", "push", "refs/heads/main"), False),
    ("private pull request", _event("private", "pull_request", "refs/pull/1/merge"), False),
    ("private manual run", _event("private", "workflow_dispatch", "refs/heads/main"), True),
    ("private release tag", _event("private", "push", "refs/tags/v0.1.0"), True),
    ("public push to main", _event("public", "push", "refs/heads/main"), True),
    ("public pull request", _event("public", "pull_request", "refs/pull/1/merge"), True),
]


# A scheduled run, which a private repository pays for as it pays for a push.
SCHEDULED = [
    ("private weekly run", _event("private", "schedule", "refs/heads/main"), False),
    ("public weekly run", _event("public", "schedule", "refs/heads/main"), True),
]


def _jobs() -> list[tuple[str, str, dict[str, Any]]]:
    found = []
    for path in WORKFLOWS:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in document["jobs"].items():
            found.append((path.name, name, job))
    return found


def _billed_above_ubuntu() -> list[tuple[str, str, dict[str, Any]]]:
    """Non-ubuntu jobs: macOS bills at 10x, Windows at 2x."""
    return [
        (workflow, name, job)
        for workflow, name, job in _jobs()
        if not str(job.get("runs-on", "")).startswith("ubuntu-")
    ]


def test_the_macos_and_windows_jobs_exist() -> None:
    """Without them the billing sweep below passes over nothing."""
    billed = {(w, n) for w, n, _ in _billed_above_ubuntu()}
    assert {("ci.yml", "test-macos"), ("ci.yml", "test-windows")} <= billed


def _started_by(triggers: dict[str, Any], context: dict[str, str]) -> bool:
    """Whether a workflow with these `on:` triggers starts for the event; `paths` is ignored."""
    name = context["github.event_name"]
    if name not in triggers:
        return False
    if name != "push":
        return True
    filters = triggers["push"] or {}
    ref = context["github.ref"]
    kind, other = ("tags", "branches") if ref.startswith("refs/tags/") else ("branches", "tags")
    if kind in filters:
        short = ref.split("/", 2)[2]
        return any(fnmatch.fnmatchcase(short, pattern) for pattern in filters[kind])
    # A push filtered on the other kind of ref alone never starts for this one.
    return other not in filters


def _runs(workflow: str, job: dict[str, Any], context: dict[str, str]) -> bool:
    # A job with no `if:` runs on every event its workflow starts for.
    return _started_by(_triggers(_workflow(workflow)), context) and _runs_on(job, context)


@pytest.mark.parametrize(
    ("label", "context", "allowed"), EVENTS + SCHEDULED, ids=[e[0] for e in EVENTS + SCHEDULED]
)
def test_a_job_billed_above_ubuntu_runs_only_where_adr_004_allows(
    label: str, context: dict[str, str], allowed: bool
) -> None:
    for workflow, name, job in _billed_above_ubuntu():
        runs = _runs(workflow, job, context)
        assert allowed or not runs, f"{workflow} / {name} on a {label}: runs={runs}"


@pytest.mark.parametrize("name", ["test-macos", "test-windows"])
@pytest.mark.parametrize(("label", "context", "allowed"), EVENTS, ids=[e[0] for e in EVENTS])
def test_the_macos_and_windows_tests_run_wherever_adr_004_allows(
    label: str, context: dict[str, str], allowed: bool, name: str
) -> None:
    """Allowed and skipped loses the coverage ADR-004 pays for."""
    runs = _runs("ci.yml", _job("ci.yml", name), context)
    assert runs == allowed, f"ci.yml / {name} on a {label}: runs={runs}"


def test_the_windows_tests_keep_the_macos_guard() -> None:
    """A change to when macOS runs changes when Windows runs, on events not listed above too."""
    assert _job("ci.yml", "test-windows")["if"] == _job("ci.yml", "test-macos")["if"]


# When e2e runs: on every push to main and pull request, and weekly once public.
E2E = {
    "private push to main": True,
    "private pull request": True,
    "private manual run": False,
    "private release tag": False,
    "public push to main": True,
    "public pull request": True,
    "private weekly run": False,
    "public weekly run": True,
}


@pytest.mark.parametrize(
    ("label", "context"),
    [(label, context) for label, context, _ in EVENTS + SCHEDULED],
    ids=[e[0] for e in EVENTS + SCHEDULED],
)
def test_the_end_to_end_run_is_weekly_once_the_repository_is_public(
    label: str, context: dict[str, str]
) -> None:
    """Its wheel installs with the newest releases the dependency ranges allow, so a weekly run
    shows one that breaks a fresh install; while private, ADR-004 keeps those minutes."""
    assert _runs("e2e.yml", _job("e2e.yml", "e2e"), context) is E2E[label]


def test_the_end_to_end_schedule_fires_once_a_week() -> None:
    """One minute of one hour on one weekday, in every month."""
    (entry,) = _triggers(_workflow("e2e.yml"))["schedule"]
    minute, hour, day, month, weekday = entry["cron"].split()
    assert (day, month) == ("*", "*"), entry["cron"]
    assert all(field.isdigit() for field in (minute, hour, weekday)), entry["cron"]


@pytest.mark.parametrize(
    ("triggers", "context", "starts"),
    [
        ({"push": {"branches": ["main"]}}, _event("public", "push", "refs/tags/v1"), False),
        ({"push": {"branches": ["main"]}}, _event("public", "push", "refs/heads/main"), True),
        ({"push": {"branches": ["main"]}}, _event("public", "push", "refs/heads/dev"), False),
        ({"push": {"tags": ["v*"]}}, _event("public", "push", "refs/heads/main"), False),
        ({"push": {"tags": ["v*"]}}, _event("public", "push", "refs/tags/v0.1.0"), True),
        ({"push": {"tags": ["v*"]}}, _event("public", "push", "refs/tags/x0.1.0"), False),
        (
            {"push": {"branches": ["main"], "tags": ["v*"]}},
            _event("public", "push", "refs/tags/v1"),
            True,
        ),
        ({"push": None}, _event("public", "push", "refs/tags/v1"), True),
        ({"push": {"paths": ["a.py"]}}, _event("public", "push", "refs/heads/main"), True),
        ({"pull_request": None}, _event("public", "pull_request", "refs/pull/1/merge"), True),
        ({"workflow_dispatch": None}, _event("public", "push", "refs/heads/main"), False),
    ],
    ids=lambda value: str(value)[:48] if not isinstance(value, bool) else str(value),
)
def test_a_workflow_starts_only_for_the_events_its_triggers_name(
    triggers: dict[str, Any], context: dict[str, str], starts: bool
) -> None:
    assert _started_by(triggers, context) == starts


def test_an_unknown_guard_shape_is_refused_rather_than_read_as_true() -> None:
    with pytest.raises(ValueError, match="no rule for the guard atom"):
        _holds("github.ref != 'refs/heads/main'", _event("private", "push", "refs/heads/main"))


def test_an_and_binds_tighter_than_an_or() -> None:
    context = _event("public", "push", "refs/tags/v1")
    assert _holds("github.event_name == 'push' && github.ref_type == 'tag'", context)
    assert not _holds("github.event_name == 'push' && github.ref_type == 'branch'", context)
    assert _holds(
        "github.ref_type == 'branch' && github.event_name == 'push' || github.ref_type == 'tag'",
        context,
    )


@pytest.mark.parametrize(
    "expression",
    [
        "github.ref_type == 'branch' && github.ref != 'x'",
        "github.ref_type == 'tag' || github.ref != 'x'",
    ],
)
def test_an_unknown_atom_is_refused_even_where_the_answer_is_known(expression: str) -> None:
    with pytest.raises(ValueError, match="no rule for the guard atom"):
        _holds(expression, _event("public", "push", "refs/tags/x"))


# A commit, which nobody can move to other code after review, as a tag or a branch can be.
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _unpinned(documents: dict[str, dict[str, Any]]) -> list[str]:
    found = []
    for workflow, document in documents.items():
        for name, job in document["jobs"].items():
            steps = [job] if "uses" in job else job.get("steps", [])
            found += [
                f"{workflow} / {name}: {step['uses']}"
                for step in steps
                if "uses" in step
                and not step["uses"].startswith("./")
                and not PINNED.match(step["uses"])
            ]
    return found


def test_every_action_a_workflow_uses_is_pinned_to_a_commit() -> None:
    documents = {path.name: yaml.safe_load(path.read_text(encoding="utf-8")) for path in WORKFLOWS}
    assert _unpinned(documents) == []


def test_the_pin_check_finds_a_tag_a_branch_and_a_short_commit() -> None:
    steps = [
        {"uses": "actions/checkout@v7"},
        {"uses": "owner/repo@main"},
        {"uses": "owner/repo@3d3c42e"},
        {"uses": "owner/repo/path@" + "3d3c42e5" * 5},
        {"uses": "./.github/actions/local"},
        {"run": "true"},
    ]
    planted = {"x.yml": {"jobs": {"a": {"steps": steps}, "b": {"uses": "o/r/w.yml@v1"}}}}
    assert _unpinned(planted) == [
        "x.yml / a: actions/checkout@v7",
        "x.yml / a: owner/repo@main",
        "x.yml / a: owner/repo@3d3c42e",
        "x.yml / b: o/r/w.yml@v1",
    ]


# The release workflow.


def _workflow(name: str) -> dict[str, Any]:
    document = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _job(workflow: str, job: str) -> dict[str, Any]:
    found = _workflow(workflow)["jobs"][job]
    assert isinstance(found, dict)
    return found


def _step(workflow: str, job: str, name: str) -> dict[str, Any]:
    (step,) = [step for step in _job(workflow, job)["steps"] if step.get("name") == name]
    assert isinstance(step, dict)
    return step


def _step_names(workflow: str, job: str) -> list[str]:
    return [step.get("name", step.get("uses", "")) for step in _job(workflow, job)["steps"]]


CI_CHECK = "Require a green ci run on main for this commit"
CANONICAL = "Check that the version is canonical PEP 440"
TAG_MATCH = "Check that the tag matches the version"
CHANGELOG = "Take this version's section from CHANGELOG.md"
NOTES_UPLOAD = "Upload the release notes"
BUILD = "uv build"
FILES = "Check the built files"
TWINE = "twine check --strict, with the upload action's twine"
DIST_UPLOAD = "Upload dist/"

PUSHED_TAG = _event("public", "push", "refs/tags/v0.1.0")
MANUAL_ON_MAIN = _event("public", "workflow_dispatch", "refs/heads/main")
MANUAL_ON_A_TAG = _event("public", "workflow_dispatch", "refs/tags/v0.1.0")


def _runs_on(guarded: dict[str, Any], context: dict[str, str]) -> bool:
    return _holds(guarded["if"], context) if "if" in guarded else True


def test_the_build_job_may_read_ci_runs_and_nothing_it_could_change() -> None:
    assert _workflow("release.yml")["permissions"] == {"contents": "read"}
    assert _job("release.yml", "build")["permissions"] == {"contents": "read", "actions": "read"}


def test_the_build_starts_by_asking_whether_ci_passed_on_main_for_this_commit() -> None:
    """First, so a tag on a commit ci never passed builds nothing; on every trigger."""
    (first, *_) = _job("release.yml", "build")["steps"]
    assert first["name"] == CI_CHECK
    assert "if" not in first
    assert first["env"] == {"GH_TOKEN": "${{ github.token }}"}


def test_the_checks_come_before_the_build_and_the_upload_after_all_of_them() -> None:
    names = _step_names("release.yml", "build")
    order = [CI_CHECK, CANONICAL, TAG_MATCH, CHANGELOG, BUILD, FILES, TWINE, DIST_UPLOAD]
    assert [name for name in names if name in order] == order
    assert names.index(NOTES_UPLOAD) > names.index(CHANGELOG)


@pytest.mark.parametrize("name", [TAG_MATCH, CHANGELOG, NOTES_UPLOAD])
def test_a_tag_check_runs_on_a_pushed_tag_and_on_nothing_else(name: str) -> None:
    step = _step("release.yml", "build", name)
    assert _runs_on(step, PUSHED_TAG)
    assert not _runs_on(step, MANUAL_ON_MAIN)
    assert not _runs_on(step, MANUAL_ON_A_TAG)


@pytest.mark.parametrize("name", [CI_CHECK, CANONICAL, BUILD, FILES, TWINE, DIST_UPLOAD])
def test_a_check_every_build_needs_runs_on_every_trigger(name: str) -> None:
    step = _step("release.yml", "build", name)
    assert all(_runs_on(step, event) for event in (PUSHED_TAG, MANUAL_ON_MAIN, MANUAL_ON_A_TAG))


def test_the_github_release_carries_the_notes_the_build_took() -> None:
    upload = _step("release.yml", "build", NOTES_UPLOAD)
    notes = "${{ runner.temp }}/notes/release-notes.md"
    assert upload["with"]["name"] == "release-notes"
    assert upload["with"]["path"] == notes
    assert upload["with"]["if-no-files-found"] == "error"
    assert (
        notes.replace("${{ runner.temp }}", "$RUNNER_TEMP")
        in (_step("release.yml", "build", CHANGELOG)["run"])
    )
    steps = _job("release.yml", "github-release")["steps"]
    (download,) = [s for s in steps if s.get("with", {}).get("name") == "release-notes"]
    assert download["with"]["path"] == "notes"
    create = _step("release.yml", "github-release", "Create the GitHub release")
    assert "--notes-file notes/release-notes.md" in create["run"]
    # The section is read once, before the build; nothing after the upload reads CHANGELOG.md.
    assert "CHANGELOG.md" not in yaml.safe_dump(_job("release.yml", "github-release"))


def test_twine_checks_the_files_strictly_with_the_upload_actions_versions() -> None:
    """The upload action runs twine 7.0.0 on packaging 26.2 without --strict."""
    run = _step("release.yml", "build", TWINE)["run"]
    assert "uvx --from twine==7.0.0 --with packaging==26.2 twine check --strict dist/*" in run


# Steps run under bash with their `${{ }}` inputs given as the environment they arrive in.
needs_bash = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="GitHub runs these steps under bash on ubuntu",
)


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _uv_runs_python(*, requires: str = "") -> str:
    """A `uv` for which `uv run ... -- python ARGS` runs ARGS under this interpreter.

    The runner's Python has nothing installed, so a run needing a package must name `requires`.
    """
    check = f'case " $* " in *" {requires}"*) ;; *) exit 97 ;; esac\n' if requires else ""
    return check + (
        'while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done\n'
        "shift 2\n"
        f'exec {shlex.quote(sys.executable)} "$@"\n'
    )


UV_RUNS_PYTHON = _uv_runs_python(requires="--with packaging==")


def _run_step(
    step: dict[str, Any],
    workspace: Path,
    env: dict[str, str],
    stubs: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a step's script the way the runner does, in `workspace`, with only `env` set."""
    runner = workspace.parent / f"{workspace.name}-runner"
    (runner / "bin").mkdir(parents=True)
    (runner / "temp").mkdir()
    for name, body in (stubs or {}).items():
        _stub(runner / "bin", name, body)
    script = runner / "step.sh"
    script.write_text(step["run"], encoding="utf-8")
    environment = {
        "PATH": f"{runner / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(runner),
        "RUNNER_TEMP": str(runner / "temp"),
        "GITHUB_OUTPUT": str(runner / "output"),
        "GITHUB_ENV": str(runner / "env"),
        **env,
    }
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _outputs(workspace: Path) -> dict[str, str]:
    path = workspace.parent / f"{workspace.name}-runner" / "output"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return dict(line.split("=", 1) for line in lines)


GH_RECORDS = """printf '%s\n' "$@" > "$HOME/gh-args"
[ -z "$GH_FAILS" ] || exit 1
printf '%s\n' "$GH_TOTAL"
"""


def _ci_check(
    tmp_path: Path, total: str, *, fails: bool = False
) -> subprocess.CompletedProcess[str]:
    return _run_step(
        _step("release.yml", "build", CI_CHECK),
        tmp_path / "work",
        {
            "GITHUB_REPOSITORY": "hakanbogan/obelize",
            "GITHUB_SHA": "0123abcd" * 5,
            "GH_TOTAL": total,
            "GH_FAILS": "yes" if fails else "",
        },
        {"gh": GH_RECORDS},
    )


@needs_bash
@pytest.mark.parametrize("total", ["1", "12"])
def test_the_ci_check_asks_for_a_successful_ci_run_on_main_at_this_commit(
    tmp_path: Path, total: str
) -> None:
    """A pull request from a fork's own `main` is listed under `branch=main` too; a push run is
    the one that shows the commit reached this repository's main."""
    (tmp_path / "work").mkdir()
    assert _ci_check(tmp_path, total).returncode == 0
    args = (tmp_path / "work-runner" / "gh-args").read_text(encoding="utf-8").splitlines()
    assert args[0] == "api"
    assert args[2:] == ["--jq", ".total_count"]
    url = urlsplit(args[1])
    assert url.path == "repos/hakanbogan/obelize/actions/workflows/ci.yml/runs"
    assert parse_qs(url.query, strict_parsing=True) == {
        "head_sha": ["0123abcd" * 5],
        "branch": ["main"],
        "event": ["push"],
        "status": ["success"],
    }


@needs_bash
@pytest.mark.parametrize(
    ("total", "fails"),
    [("0", False), ("null", False), ("", False), ("", True)],
    ids=["none", "no count", "nothing printed", "gh fails"],
)
def test_the_ci_check_stops_the_build_without_a_green_run(
    tmp_path: Path, total: str, fails: bool
) -> None:
    (tmp_path / "work").mkdir()
    result = _ci_check(tmp_path, total, fails=fails)
    assert result.returncode != 0
    if not fails:
        assert "::error::ci.yml has not passed on main for" in result.stdout


def _workspace(tmp_path: Path, version: str, changelog: str = "") -> Path:
    workspace = tmp_path / "work"
    (workspace / "src/obelize").mkdir(parents=True)
    (workspace / "src/obelize/__init__.py").write_text(
        f'"""Docstring."""\n\n__version__ = "{version}"\n\n__all__ = ["__version__"]\n',
        encoding="utf-8",
    )
    (workspace / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return workspace


@needs_bash
@pytest.mark.parametrize("version", ["0.1.0", "0.1.0.dev7", "0.1.0a1", "1.2.3.post1", "0.2"])
def test_a_canonical_version_passes_and_is_handed_on(tmp_path: Path, version: str) -> None:
    workspace = _workspace(tmp_path, version)
    step = _step("release.yml", "build", CANONICAL)
    result = _run_step(step, workspace, {}, {"uv": UV_RUNS_PYTHON})
    assert result.returncode == 0, result.stdout + result.stderr
    assert _outputs(workspace) == {"version": version}


@needs_bash
@pytest.mark.parametrize(
    ("version", "canonical"),
    [
        ("0.1.0-rc1", "0.1.0rc1"),
        ("v0.1.0", "0.1.0"),
        ("0.1.0.RC1", "0.1.0rc1"),
        ("1.0-a.1", "1.0a1"),
    ],
)
def test_a_version_pep_440_would_rewrite_stops_the_build(
    tmp_path: Path, version: str, canonical: str
) -> None:
    """PyPI and the page's tag links use the normal form, the tag check the text as written."""
    workspace = _workspace(tmp_path, version)
    step = _step("release.yml", "build", CANONICAL)
    result = _run_step(step, workspace, {}, {"uv": UV_RUNS_PYTHON})
    assert result.returncode != 0
    assert f"write it as '{canonical}'" in result.stdout
    assert _outputs(workspace) == {}


@needs_bash
@pytest.mark.parametrize(
    ("version", "error"),
    [
        ("banana", "__version__ 'banana' is not a PEP 440 version"),
        ("", "could not read __version__"),
    ],
)
def test_a_version_that_is_not_pep_440_stops_the_build(
    tmp_path: Path, version: str, error: str
) -> None:
    workspace = _workspace(tmp_path, version)
    step = _step("release.yml", "build", CANONICAL)
    result = _run_step(step, workspace, {}, {"uv": UV_RUNS_PYTHON})
    assert result.returncode != 0
    assert f"::error::{error}" in result.stdout
    assert _outputs(workspace) == {}


@needs_bash
@pytest.mark.parametrize(
    ("tag", "passes"), [("v0.1.0", True), ("v0.1.1", False), ("0.1.0", False), ("v0.1.0rc1", False)]
)
def test_the_tag_must_name_the_version(tmp_path: Path, tag: str, passes: bool) -> None:
    workspace = _workspace(tmp_path, "0.1.0")
    step = _step("release.yml", "build", TAG_MATCH)
    result = _run_step(step, workspace, {"GITHUB_REF_NAME": tag, "VERSION": "0.1.0"})
    assert (result.returncode == 0) == passes, result.stdout


SECTIONED = """# Changelog

## [Unreleased]

- Fixes the `## [0.1.0]` heading's date.

## [0.1.0] - 2026-10-01

### Added

- The first release.

## [0.1.0.dev1] - 2026-09-01

- A rehearsal.
"""


@needs_bash
def test_the_notes_are_this_versions_section_and_nothing_around_it(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "0.1.0", SECTIONED)
    step = _step("release.yml", "build", CHANGELOG)
    result = _run_step(step, workspace, {"VERSION": "0.1.0"})
    assert result.returncode == 0, result.stdout
    notes = tmp_path / "work-runner" / "temp" / "notes" / "release-notes.md"
    assert notes.read_text(encoding="utf-8") == "\n### Added\n\n- The first release.\n\n"


@needs_bash
@pytest.mark.parametrize(
    ("version", "changelog"),
    [
        ("0.1.0", "# Changelog\n\n## [Unreleased]\n\n- Later.\n"),
        ("0.1.0", "# Changelog\n\n## [0.1.0] - 2026-10-01\n\n  \n\n## [0.0.9]\n\n- Old.\n"),
        # A heading that only starts with the version names another one.
        ("0.1.0", "## [0.1.0.dev1] - 2026-09-01\n\n- A rehearsal.\n"),
        # A dot in the version is not a wildcard.
        ("0.1.0", "## [0x1y0] - 2026-09-01\n\n- Not this one.\n"),
    ],
    ids=["missing", "empty", "longer version", "dot as wildcard"],
)
def test_a_release_without_a_changelog_section_stops_before_the_build(
    tmp_path: Path, version: str, changelog: str
) -> None:
    workspace = _workspace(tmp_path, version, changelog)
    step = _step("release.yml", "build", CHANGELOG)
    result = _run_step(step, workspace, {"VERSION": version})
    assert result.returncode != 0
    assert f"CHANGELOG.md has no '## [{version}]' section" in result.stdout


def _dist(workspace: Path, *names: str) -> None:
    (workspace / "dist").mkdir()
    for name in names:
        (workspace / "dist" / name).write_bytes(b"")


@needs_bash
@pytest.mark.parametrize(
    ("files", "passes"),
    [
        ((".gitignore", "obelize-0.1.0-py3-none-any.whl", "obelize-0.1.0.tar.gz"), True),
        (("obelize-0.1.0-py3-none-any.whl",), False),
        (("obelize-0.1.0.tar.gz",), False),
        (("obelize-0.1.0-py3-none-any.whl", "obelize-0.1.0.tar.gz", "obelize-0.0.9.tar.gz"), False),
        (("obelize-0.1.0rc1-py3-none-any.whl", "obelize-0.1.0rc1.tar.gz"), False),
        (("obelize-0.1.0-py3-none-any.whl", "obelize-0.1.0.zip"), False),
        (("obelize-0.1.0-cp312-abi3-win_amd64.whl", "obelize-0.1.0.tar.gz"), False),
    ],
    ids=[
        "exact",
        "no sdist",
        "no wheel",
        "a third file",
        "another version",
        "a zip sdist",
        "a platform wheel",
    ],
)
def test_the_build_hands_on_exactly_this_versions_wheel_and_sdist(
    tmp_path: Path, files: tuple[str, ...], passes: bool
) -> None:
    workspace = _workspace(tmp_path, "0.1.0")
    _dist(workspace, *files)
    result = _run_step(_step("release.yml", "build", FILES), workspace, {"VERSION": "0.1.0"})
    assert (result.returncode == 0) == passes, result.stdout


# The build backend.

CONSTRAINTS = ".github/build-constraints.txt"


def _pins() -> dict[str, Version]:
    """The constraints file, one `name==version` a line."""
    pins: dict[str, Version] = {}
    for line in (ROOT / CONSTRAINTS).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            requirement = Requirement(line)
            (specifier,) = requirement.specifier
            assert specifier.operator == "==", line
            pins[requirement.name] = Version(specifier.version)
    return pins


def test_the_constraints_pin_every_build_requirement_inside_its_range() -> None:
    """Someone rebuilding the sdist gets pyproject.toml's range; a release gets the pin in it."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        requires = [Requirement(r) for r in tomllib.load(handle)["build-system"]["requires"]]
    pins = _pins()
    assert sorted(pins) == sorted(requirement.name for requirement in requires)
    for requirement in requires:
        assert pins[requirement.name] in requirement.specifier, requirement


def _builds_a_distribution(job: dict[str, Any]) -> bool:
    return any(re.search(r"\buv build\b", step.get("run", "")) for step in job["steps"])


def test_every_job_that_builds_a_distribution_builds_with_the_pinned_backend() -> None:
    """The wheel ci and e2e test is built by the backend that builds the one PyPI gets."""
    building = set()
    for workflow, name, job in _jobs():
        if _builds_a_distribution(job):
            building.add((workflow, name))
            for step in job["steps"]:
                if "uv build" in step.get("run", ""):
                    env = {**job.get("env", {}), **step.get("env", {})}
                    assert env.get("UV_BUILD_CONSTRAINT") == CONSTRAINTS, (workflow, name)
    assert building == {("ci.yml", "smoke"), ("e2e.yml", "e2e"), ("release.yml", "build")}


def _triggers(document: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the bare key `on` as true.
    triggers = document[True]
    assert isinstance(triggers, dict)
    return triggers


def _setup_uv_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in job["steps"] if s.get("uses", "").startswith("astral-sh/setup-uv@")]


def test_a_run_on_a_release_tag_restores_no_cache() -> None:
    """Another ref can write the cache; setup-uv's default, `auto`, is off on a tag push."""
    tagged = []
    for path in WORKFLOWS:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "tags" not in (_triggers(document).get("push") or {}):
            continue
        tagged.append(path.name)
        for job in document["jobs"].values():
            for step in job.get("steps", []):
                assert not step.get("uses", "").startswith("actions/cache"), path.name
            for step in _setup_uv_steps(job):
                assert step.get("with", {}).get("enable-cache", "auto") in ("auto", False)
    assert tagged == ["ci.yml", "release.yml"]


@pytest.mark.parametrize("workflow", ["release.yml", "post-release.yml"])
def test_what_uploads_or_checks_a_release_restores_no_cache_on_any_trigger(workflow: str) -> None:
    """A manual run uploads too, and `auto` restores a cache on one; an install check that
    reads a cache is not checking the index."""
    steps = [step for job in _workflow(workflow)["jobs"].values() for step in job["steps"]]
    setup = [step for step in steps if step.get("uses", "").startswith("astral-sh/setup-uv@")]
    assert setup
    assert all(step["with"]["enable-cache"] is False for step in setup)


# The rehearsal.

REHEARSAL = "Number the rehearsal build"


def test_the_release_runs_on_a_v_tag_and_by_hand_and_on_nothing_else() -> None:
    assert _triggers(_workflow("release.yml")) == {
        "push": {"tags": ["v*"]},
        "workflow_dispatch": None,
    }


@pytest.mark.parametrize(
    ("job", "needs", "on_a_tag", "by_hand"),
    [
        ("build", None, True, True),
        ("publish", "build", True, False),
        ("github-release", "publish", True, False),
        ("publish-testpypi", "build", False, True),
    ],
)
def test_a_tag_publishes_to_pypi_and_a_manual_run_only_to_testpypi(
    job: str, needs: str | None, on_a_tag: bool, by_hand: bool
) -> None:
    """A manual run on a tag is still a rehearsal: it never reaches PyPI or a GitHub release."""
    found = _job("release.yml", job)
    assert found.get("needs") == needs
    assert _runs_on(found, PUSHED_TAG) == on_a_tag
    assert _runs_on(found, MANUAL_ON_MAIN) == by_hand
    assert _runs_on(found, MANUAL_ON_A_TAG) == by_hand


PUBLISH_ACTION = "pypa/gh-action-pypi-publish@"


@pytest.mark.parametrize(
    ("job", "environment", "url", "repository"),
    [
        ("publish", "pypi", "https://pypi.org/p/obelize", None),
        (
            "publish-testpypi",
            "testpypi",
            "https://test.pypi.org/p/obelize",
            "https://test.pypi.org/legacy/",
        ),
    ],
)
def test_each_upload_goes_to_its_own_index_from_its_own_environment(
    job: str, environment: str, url: str, repository: str | None
) -> None:
    found = _job("release.yml", job)
    assert found["environment"] == {"name": environment, "url": url}
    (upload,) = [s for s in found["steps"] if s.get("uses", "").startswith(PUBLISH_ACTION)]
    assert upload["with"].get("repository-url") == repository
    assert upload["with"]["packages-dir"] == "dist"


def test_both_uploads_run_the_same_pinned_action() -> None:
    uses = {
        step["uses"]
        for job in ("publish", "publish-testpypi")
        for step in _job("release.yml", job)["steps"]
        if step.get("uses", "").startswith(PUBLISH_ACTION)
    }
    assert len(uses) == 1


def test_the_rehearsal_is_not_a_line_to_uncomment() -> None:
    """The workflow that uploads to PyPI is the one the rehearsal ran, unedited."""
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert text.count("repository-url") == 1
    assert not re.search(r"^\s*#.*repository-url", text, re.MULTILINE)


def test_only_an_upload_job_can_ask_for_an_oidc_token_and_each_waits_in_an_environment() -> None:
    """The approval a release waits for is set on the environment, so no upload may skip one."""
    minting = set()
    for path in WORKFLOWS:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "id-token" not in (document.get("permissions") or {}), path.name
        for name, job in document["jobs"].items():
            if (job.get("permissions") or {}).get("id-token") == "write":
                minting.add((path.name, name, job["environment"]["name"]))
    assert minting == {
        ("release.yml", "publish", "pypi"),
        ("release.yml", "publish-testpypi", "testpypi"),
    }


def test_the_rehearsal_is_numbered_by_hand_only_and_before_the_version_check() -> None:
    step = _step("release.yml", "build", REHEARSAL)
    assert not _runs_on(step, PUSHED_TAG)
    assert _runs_on(step, MANUAL_ON_MAIN)
    assert _runs_on(step, MANUAL_ON_A_TAG)
    names = _step_names("release.yml", "build")
    assert names.index("Checkout") < names.index(REHEARSAL) < names.index(CANONICAL)


@needs_bash
@pytest.mark.parametrize(
    ("version", "rehearsal"),
    [("0.1.0.dev0", "0.1.0.dev42"), ("0.1.0", "0.1.0.dev42"), ("0.2.0a1.dev3", "0.2.0a1.dev42")],
)
def test_each_rehearsal_builds_a_version_testpypi_has_not_seen(
    tmp_path: Path, version: str, rehearsal: str
) -> None:
    """TestPyPI takes a file name once; the run number makes each rehearsal's names new."""
    workspace = _workspace(tmp_path, version)
    before = (workspace / "src/obelize/__init__.py").read_text(encoding="utf-8")
    step = _step("release.yml", "build", REHEARSAL)
    result = _run_step(step, workspace, {"GITHUB_RUN_NUMBER": "42"})
    assert result.returncode == 0, result.stdout + result.stderr
    after = (workspace / "src/obelize/__init__.py").read_text(encoding="utf-8")
    assert after == before.replace(f'"{version}"', f'"{rehearsal}"')
    assert after != before


# The install check after a release.

POST_RELEASE = "post-release.yml"
CHOOSE = "Choose what to install"
INSTALL = "Install obelize with ${{ matrix.installer }}"
RUN = "Run --version, --help, pack validate and a scan of the example"


def test_the_install_check_runs_only_by_hand_given_an_index_and_a_version() -> None:
    triggers = _triggers(_workflow(POST_RELEASE))
    assert list(triggers) == ["workflow_dispatch"]
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"index", "version"}
    assert inputs["index"]["type"] == "choice"
    assert inputs["index"]["options"] == ["pypi", "testpypi"]
    assert inputs["version"]["required"] is True


def test_the_install_check_installs_on_each_os_in_each_way_the_readme_gives() -> None:
    job = _job(POST_RELEASE, "install")
    assert job["runs-on"] == "${{ matrix.os }}"
    assert job["strategy"]["fail-fast"] is False
    matrix = job["strategy"]["matrix"]
    assert sorted(matrix["os"]) == ["macos-latest", "ubuntu-latest", "windows-latest"]
    assert sorted(matrix["installer"]) == ["pip", "pipx", "uvx"]
    assert job["defaults"]["run"]["shell"] == "bash"
    install = _step(POST_RELEASE, "install", INSTALL)["run"]
    for command in (
        'uvx --from "$SPEC" obelize',
        'pipx install --python "$(uv python find 3.12)" "$SPEC"',
        '-m pip install "$SPEC"',
    ):
        assert command in install
    names = _step_names(POST_RELEASE, "install")
    assert names.index(CHOOSE) < names.index(INSTALL) < names.index(RUN)


def test_no_script_expands_an_input_or_event_text_into_its_own_source() -> None:
    """A value reaches a script through the environment, where the shell cannot run it."""
    for workflow, name, job in _jobs():
        for step in job.get("steps", []):
            run = step.get("run", "")
            assert "${{ inputs." not in run, (workflow, name, step.get("name"))
            assert "${{ github.event." not in run, (workflow, name, step.get("name"))


def _env_file(workspace: Path) -> str:
    path = workspace.parent / f"{workspace.name}-runner" / "env"
    return path.read_text(encoding="utf-8") if path.exists() else ""


CURL_TESTPYPI = """printf '%s\\n' "$@" > "$HOME/curl-args"
printf '%s' "$TESTPYPI_JSON"
"""


def _choose(
    tmp_path: Path, index: str, version: str, json: str = ""
) -> tuple[subprocess.CompletedProcess[str], Path]:
    workspace = tmp_path / "work"
    workspace.mkdir()
    step = _step(POST_RELEASE, "install", CHOOSE)
    result = _run_step(
        step,
        workspace,
        {"INDEX": index, "VERSION": version, "TESTPYPI_JSON": json},
        {"curl": CURL_TESTPYPI, "uv": _uv_runs_python()},
    )
    return result, workspace


@needs_bash
def test_a_pypi_install_names_the_version_on_pypi(tmp_path: Path) -> None:
    result, workspace = _choose(tmp_path, "pypi", "0.1.0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _env_file(workspace) == "SPEC=obelize==0.1.0\n"


WHEEL = "https://test-files.pythonhosted.org/packages/ab/cd/obelize-0.1.0.dev5-py3-none-any.whl"
SDIST = "https://test-files.pythonhosted.org/packages/ef/01/obelize-0.1.0.dev5.tar.gz"


@needs_bash
def test_a_testpypi_install_takes_only_obelizes_own_wheel_from_testpypi(tmp_path: Path) -> None:
    """Dependencies still resolve on PyPI, where nobody else can upload a typer."""
    files = [{"packagetype": "sdist", "url": SDIST}, {"packagetype": "bdist_wheel", "url": WHEEL}]
    result, workspace = _choose(tmp_path, "testpypi", "0.1.0.dev5", json.dumps({"urls": files}))
    assert result.returncode == 0, result.stdout + result.stderr
    assert _env_file(workspace) == f"SPEC={WHEEL}\n"
    args = (tmp_path / "work-runner" / "curl-args").read_text(encoding="utf-8").splitlines()
    assert args[-1] == "https://test.pypi.org/pypi/obelize/0.1.0.dev5/json"


@needs_bash
def test_a_testpypi_release_without_a_wheel_stops_the_check(tmp_path: Path) -> None:
    files = [{"packagetype": "sdist", "url": SDIST}]
    result, workspace = _choose(tmp_path, "testpypi", "0.1.0.dev5", json.dumps({"urls": files}))
    assert result.returncode != 0
    assert _env_file(workspace) == ""


@needs_bash
@pytest.mark.parametrize(
    "version", ["latest", "0.1.0; touch pwned", "0.1.0\nSPEC=x", "v0.1.0", "0.1.0-rc1", ""]
)
def test_a_version_that_is_not_a_plain_release_version_stops_the_check(
    tmp_path: Path, version: str
) -> None:
    result, workspace = _choose(tmp_path, "pypi", version)
    assert result.returncode != 0
    assert _env_file(workspace) == ""
    assert not (workspace / "pwned").exists()


OBELIZE_RECORDS = """printf '%s\\n' "$*" >> "$HOME/obelize-calls"
case "$1" in
  --version) printf 'obelize %s\\r\\n' "$PRINTS_VERSION" ;;
  scan) printf '{"counts": {"findings": %s}}\\r\\n' "$FINDINGS" ;;
esac
"""

UVX_RUNS_OBELIZE = """[ "$1" = --from ] && [ "$2" = "$SPEC" ] && [ "$3" = obelize ] || exit 98
shift 3
exec obelize "$@"
"""


def _run_checks(
    tmp_path: Path, installer: str, prints: str, findings: str
) -> subprocess.CompletedProcess[str]:
    workspace = tmp_path / "work"
    (workspace / "examples/quickstart").mkdir(parents=True)
    (workspace / "examples/quickstart/app.py").write_text("import x\n", encoding="utf-8")
    runner = tmp_path / "work-runner"
    env = {
        "INDEX": "pypi",
        "INSTALLER": installer,
        "SPEC": "obelize==0.1.0",
        "VERSION": "0.1.0",
        "PRINTS_VERSION": prints,
        "FINDINGS": findings,
    }
    if installer != "uvx":
        env["OBELIZE"] = str(runner / "bin" / "obelize")
    stubs = {"obelize": OBELIZE_RECORDS, "uvx": UVX_RUNS_OBELIZE, "uv": _uv_runs_python()}
    return _run_step(_step(POST_RELEASE, "install", RUN), workspace, env, stubs)


@needs_bash
@pytest.mark.parametrize("installer", ["uvx", "pipx", "pip"])
def test_the_installed_command_is_run_four_ways_on_a_copy_of_the_example(
    tmp_path: Path, installer: str
) -> None:
    result = _run_checks(tmp_path, installer, "0.1.0", "5")
    assert result.returncode == 0, result.stdout + result.stderr
    temp = tmp_path / "work-runner" / "temp"
    calls = (tmp_path / "work-runner" / "obelize-calls").read_text(encoding="utf-8")
    assert calls.splitlines() == [
        "--version",
        "--help",
        "pack validate gemini/google-generativeai-to-google-genai",
        f"scan --repo {temp / 'quickstart'} --json",
    ]
    assert (temp / "quickstart" / "app.py").is_file()


@needs_bash
@pytest.mark.parametrize(
    ("prints", "findings"), [("0.0.9", "5"), ("0.1.0", "0")], ids=["another version", "no finding"]
)
def test_a_wrong_version_or_an_empty_scan_fails_the_check(
    tmp_path: Path, prints: str, findings: str
) -> None:
    result = _run_checks(tmp_path, "pip", prints, findings)
    assert result.returncode != 0
    assert "::error::" in result.stdout


# docs/RELEASING.md

PUBLISH_JOBS = ("publish", "publish-testpypi")


def _publisher_fields() -> dict[str, list[str]]:
    """The pending-publisher table: field -> [PyPI, TestPyPI], backticks dropped."""
    text = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
    section = text.split("\n## Trusted Publishing\n")[1].split("\n## ")[0]
    rows = [line.split("|")[1:-1] for line in section.splitlines() if line.startswith("| ")]
    return {cells[0].strip(): [c.strip().strip("`") for c in cells[1:]] for cells in rows[1:]}


def test_the_pending_publishers_releasing_md_lists_are_the_ones_the_uploads_present() -> None:
    """PyPI refuses an upload whose repository, workflow or environment differs by a letter."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    owner, repository = urlsplit(project["urls"]["Repository"]).path.strip("/").split("/")
    environments = [_job("release.yml", job)["environment"]["name"] for job in PUBLISH_JOBS]
    assert _publisher_fields() == {
        "PyPI Project Name": [project["name"]] * 2,
        "Owner": [owner] * 2,
        "Repository name": [repository] * 2,
        "Workflow name": ["release.yml"] * 2,
        "Environment name": environments,
    }


def test_the_pre_flight_builds_and_checks_the_files_as_the_release_does() -> None:
    text = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
    pre_flight = text.split("\n## Pre-flight\n")[1]
    assert f"UV_BUILD_CONSTRAINT={CONSTRAINTS} uv build\n" in pre_flight
    assert _step("release.yml", "build", TWINE)["run"] in pre_flight


def _link_check() -> str:
    """The command step 8 runs over the built METADATA before the upload is approved."""
    text = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")
    step = text.split("\n8. Tag.")[1].split("\n9. ")[0]
    (block,) = re.findall(r"^ {3}```bash\n(.*?)^ {3}```", step, re.MULTILINE | re.DOTALL)
    return textwrap.dedent(block).replace("<version>", "0.1.0")


# A `curl` that answers 404 for each URL in `$MISSING`, and 301 for a directory unless told to
# follow it, as GitHub sends a blob URL on to its tree; it prints what `-w` asks for.
CURL_ANSWERS = """url= follow= format=
while [ "$#" -gt 0 ]; do
  case "$1" in
    -w) format=$2; shift ;;
    -o) shift ;;
    -*L*) follow=yes ;;
    -*) ;;
    *) url=$1 ;;
  esac
  shift
done
printf '%s\\n' "$url" >> "$HOME/curl-urls"
code=200
case " $MISSING " in *" $url "*) code=404 ;; esac
case "$url" in */) [ -n "$follow" ] || code=301 ;; esac
printf "$(printf '%s' "$format" | sed -e "s|%{http_code}|$code|g" -e "s|%{url}|$url|g")"
"""

BLOB = "https://github.com/hakanbogan/obelize/blob/v0.1.0/"
# As the build writes README's links: a title after one, an image, and a link at `main`.
LINKED = (
    f"[a]({BLOB}docs/CLI.md#exit-codes) [b](#install) [c]({BLOB}docs/CLI.md#exit-codes)\n"
    f"[![h](https://raw.githubusercontent.com/hakanbogan/obelize/v0.1.0/h.png)]"
    f'({BLOB}LICENSE "Licence")\n'
    f"[j]({BLOB}examples/quickstart/) [m](https://github.com/hakanbogan/obelize/blob/main/x)\n"
)


def _checked_links(
    tmp_path: Path, description: str, missing: str = ""
) -> subprocess.CompletedProcess[str]:
    workspace = tmp_path / "work"
    (workspace / "dist").mkdir(parents=True)
    wheel = workspace / "dist" / "obelize-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "obelize-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: obelize\nVersion: 0.1.0\n"
            f"Description-Content-Type: text/markdown\n\n{description}",
        )
    # Typed at a prompt, where no pipefail stops a pipeline whose grep found nothing.
    command = f"set +o pipefail\n{_link_check()}"
    return _run_step({"run": command}, workspace, {"MISSING": missing}, {"curl": CURL_ANSWERS})


@needs_bash
def test_before_approval_every_link_at_the_tag_is_asked_for_once(tmp_path: Path) -> None:
    result = _checked_links(tmp_path, LINKED)
    assert result.returncode == 0, result.stdout + result.stderr
    asked = [f"{BLOB}LICENSE", f"{BLOB}docs/CLI.md#exit-codes", f"{BLOB}examples/quickstart/"]
    assert sorted(result.stdout.splitlines()) == [f"200 {url}" for url in asked]
    urls = (tmp_path / "work-runner" / "curl-urls").read_text(encoding="utf-8").splitlines()
    assert sorted(urls) == asked


@needs_bash
@pytest.mark.parametrize(
    ("description", "missing"),
    [(LINKED, f"{BLOB}LICENSE"), ("No link to the tag.\n", "")],
    ids=["missing", "none"],
)
def test_before_approval_a_link_the_tag_does_not_serve_or_no_link_stops_it(
    tmp_path: Path, description: str, missing: str
) -> None:
    """No link at all means the check read nothing, which is no pass."""
    result = _checked_links(tmp_path, description, missing)
    assert result.returncode != 0
    assert (f"404 {missing}" in result.stdout.splitlines()) is bool(missing)


def test_a_windows_run_reports_every_failure_and_where_a_test_hangs() -> None:
    """Without these a module that fails to import ends the session before any test runs, and a
    hang lasts until the job's timeout, which ends the run with no summary."""
    legs = [
        (job, shlex.split(step["run"]))
        for _, _, job in _jobs()
        if str(job.get("runs-on", "")).startswith("windows-")
        for step in job.get("steps", [])
        if "pytest" in step.get("run", "")
    ]
    assert legs, "no job runs the suite on Windows"
    for job, command in legs:
        options = command[command.index("pytest") + 1 :]
        assert job["strategy"]["fail-fast"] is False
        assert "-ra" in options
        assert "--continue-on-collection-errors" in options
        dumps = [int(o.partition("=")[2]) for o in options if o.startswith("faulthandler_timeout=")]
        assert dumps, "a hang would print no stack before the job's timeout ends it"
        assert dumps[0] < job["timeout-minutes"] * 60
