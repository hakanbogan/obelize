"""What the three commands do, over three repositories and every run the key lists.

The key is tests/fixtures/commands/answers.yaml. Commands run in-process through typer's runner:
coverage cannot see a subprocess, and `obelize.cli` is only argument parsing over `commands`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

from obelize.cli import app
from obelize.evidence import report
from platforms import PYTHON, copied

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "commands"
KEY: dict[str, Any] = yaml.safe_load((ROOT / "answers.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["case"]: case for case in KEY["cases"]}
COMMANDS: dict[str, str] = KEY["commands"]
PACK: str = KEY["pack"]

runner = CliRunner()

# One parameter per run. A case's runs share one working copy, in order, so `verify` and `undo`
# can point at an earlier run's folder.
RUNS = [(name, index) for name in sorted(CASES) for index in range(len(CASES[name]["runs"]))]


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *arguments],
        check=True,
        capture_output=True,
    )


def commit(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def append(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        with (root / name).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(text)


def spelled(argv: list[str], marker: Path) -> list[str]:
    """Fill in names and placeholders; `{marker}` lies outside the repo, so no scan sees it.

    It sits inside a Python string literal, where a backslash would start an escape.
    """
    return [
        COMMANDS.get(word.strip("{}"), word).format(python=PYTHON, marker=marker.as_posix())
        for word in argv
    ]


def digests(folder: Path) -> dict[str, bytes]:
    """Every file under a run folder, by its folder-relative path spelled with `/`."""
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def prepare(work: Path, case: dict[str, Any]) -> None:
    """One working copy, in the git state its key declares."""
    shutil.copytree(ROOT / case["repository"], work)
    if case["git"]["init"]:
        git(work, "init", "-q", "-b", "work")
        git(work, "config", "user.name", "obelize tests")
        git(work, "config", "user.email", "tests@obelize.invalid")
        commit(work, "the tree before obelize saw it")
    append(work, case["git"].get("appended") or {})


def invoke(work: Path, argv: list[str], marker: Path, patch: pytest.MonkeyPatch) -> Result:
    """`sys.argv` is pinned: `run.json` copies it, and in-process it would be pytest's."""
    arguments = [*spelled(argv, marker), "--repo", str(work)]
    if arguments[0] == "fix":
        arguments += ["--pack", PACK]
    patch.setattr(sys, "argv", ["obelize", *arguments])
    return runner.invoke(app, arguments, catch_exceptions=False)


def drive(
    work: Path, case: dict[str, Any], marker: Path, patch: pytest.MonkeyPatch
) -> list[dict[str, Any]]:
    """Every run of one case, in order, driven once; each state is captured as the run ends."""
    original = ROOT / case["repository"]
    created: list[Path] = []
    states: list[dict[str, Any]] = []
    for spec in case["runs"]:
        if spec.get("commit"):
            commit(work, "the tree after the last run")
        append(work, spec.get("appended") or {})
        argv = list(spec["argv"])
        target = spec.get("updates", spec.get("undo_of"))
        folder = None if target is None else created[_written(case, target)]
        before = {} if folder is None else digests(folder)
        if folder is not None:
            argv += ["--run", folder.name]
        existing = _folders(work)
        result = invoke(work, argv, marker, patch)
        if argv[0] == "fix":
            # Set difference, not the largest name: same-second run ids differ only by random hex.
            folder = (_folders(work) - existing).pop()
            created.append(folder)
        assert folder is not None
        states.append(
            {
                "case": case,
                "spec": spec,
                "work": work,
                "folder": folder,
                "before": before,
                "after": digests(folder),
                "result": result,
                "run": json.loads((folder / "run.json").read_text(encoding="utf-8")),
                "legacy": (work / "app.py").read_bytes() == (original / "app.py").read_bytes(),
                "started": marker.exists(),
            }
        )
    return states


def _folders(work: Path) -> set[Path]:
    runs = work / ".obelize" / "runs"
    return set(runs.iterdir()) if runs.is_dir() else set()


def _written(case: dict[str, Any], index: int) -> int:
    """Which run folder a `--run` points at, counting only the runs that made one."""
    return sum(1 for spec in case["runs"][:index] if spec["argv"][0] == "fix")


@pytest.fixture(scope="module")
def driven(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, int], dict[str, Any]]:
    """Every case driven once, keyed like `RUNS`."""
    root = tmp_path_factory.mktemp("commands")
    captured: dict[tuple[str, int], dict[str, Any]] = {}
    with pytest.MonkeyPatch.context() as patch:
        for name, case in CASES.items():
            work = root / name
            prepare(work, case)
            for index, one in enumerate(drive(work, case, root / f"{name}.ran", patch)):
                captured[(name, index)] = one
    return captured


@pytest.fixture
def state(
    request: pytest.FixtureRequest, driven: dict[tuple[str, int], dict[str, Any]]
) -> dict[str, Any]:
    return driven[request.param]


def parametrised(function: Any) -> Any:
    return pytest.mark.parametrize(
        "state", RUNS, ids=[f"{name}-{index}" for name, index in RUNS], indirect=True
    )(function)


@parametrised
def test_the_process_exits_with_the_code_the_table_gives_it(state: dict[str, Any]) -> None:
    assert state["result"].exit_code == state["spec"]["exit_code"], state["result"].output


@parametrised
def test_the_record_says_what_was_written(state: dict[str, Any]) -> None:
    spec, record = state["spec"], state["run"]
    if "mode" not in spec:
        return
    assert record["mode"] == spec["mode"]
    assert [row["path"] for row in record["file_edits"]] == spec["file_edits"]
    assert record["idempotent"] is spec["idempotent"]
    assert [row["code"] for row in record["refused"]] == spec["refused"]
    assert record["exit_code"] == spec["exit_code"]
    if "git_dirty" in spec:
        assert record["git_dirty"] is spec["git_dirty"]
    if "blocked" in spec:
        assert record["blocked"] == spec["blocked"]
    if "plan_files" in spec:
        planned = json.loads((state["folder"] / "plan.json").read_text(encoding="utf-8"))
        assert [row["path"] for row in planned["files"]] == spec["plan_files"]
    if "counts" in spec:
        assert {key: record["counts"][key] for key in spec["counts"]} == spec["counts"]


@parametrised
def test_the_verification_is_the_one_the_phases_allow(state: dict[str, Any]) -> None:
    """`baseline` records the order: none if the gate refused first; no after-phase if it failed."""
    spec = state["spec"]
    if "verify" not in spec:
        return
    verify = state["run"]["verify"]
    assert verify["status"] == spec["verify"]["status"]
    assert verify["reason"] == spec["verify"]["reason"]
    assert len(verify["commands"]) == spec["verify"]["commands"]
    expected = spec["verify"]["baseline"]
    if expected is None:
        assert verify["baseline"] is None
        return
    assert verify["baseline"]["status"] == expected["status"]
    assert len(verify["baseline"]["commands"]) == expected["commands"]


@parametrised
def test_the_folder_holds_what_the_mode_writes(state: dict[str, Any]) -> None:
    spec = state["spec"]
    if "mode" not in spec:
        return
    top = sorted(name for name in state["after"] if "/" not in name)
    assert top == KEY["artefacts"][spec["mode"]]
    assert (
        sorted(name for name in state["after"] if name.startswith("verify/"))
        == (spec["verify_files"])
    )
    for half, count in (("before", "before"), ("after", "after")):
        rows = [name for name in state["after"] if name.startswith(f"snapshots/{half}/")]
        assert len(rows) == spec["snapshots"][count]


@parametrised
def test_a_snapshot_is_named_by_what_is_in_it(state: dict[str, Any]) -> None:
    """`obelize undo` refuses a snapshot whose bytes disagree with its name."""
    for name, data in state["after"].items():
        if name.startswith("snapshots/"):
            assert hashlib.sha256(data).hexdigest() == name.rsplit("/", 1)[1]


@parametrised
def test_the_working_tree_is_where_the_key_leaves_it(state: dict[str, Any]) -> None:
    expected = state["spec"].get("tree")
    if expected is None:
        return
    same = state["legacy"]
    assert same is (expected == "legacy"), f"app.py is {'un' if same else ''}changed"


@parametrised
def test_a_re_verification_replaces_what_it_measured_and_keeps_what_it_did_not(
    state: dict[str, Any],
) -> None:
    spec = state["spec"]
    if "keeps" not in spec:
        return
    before, after = state["before"], state["after"]
    for kept in spec["keeps"]:
        names = [name for name in before if name == kept or name.startswith(f"{kept}/")]
        assert names, f"{kept} was not in the folder before the run"
        for name in names:
            assert after.get(name) == before[name], f"{name} moved and should not have"
    document = after["REPORT.md"].decode("utf-8")
    assert (report.SUPERSEDED in document) is spec["superseded"]
    assert (state["work"] / ".obelize" / "latest").read_text(encoding="utf-8").strip() != "", (
        "the pointer is never emptied"
    )


@parametrised
def test_undo_puts_back_what_it_wrote_and_names_what_it_would_not(
    state: dict[str, Any],
) -> None:
    spec = state["spec"]
    if "undo" not in spec:
        return
    # As the run left it: a later undo of the same run replaces the file.
    document = json.loads(state["after"]["undo.json"])
    assert document["run_id"] == state["folder"].name
    assert document["exit_code"] == spec["exit_code"]
    assert [
        {"path": row["path"], "outcome": row["outcome"], "reason": row["reason"]}
        for row in document["files"]
    ] == spec["undo"]
    shown = state["result"].stdout.splitlines()
    already = spec.get("already", [])
    for row in document["files"]:
        assert (state["folder"] / row["snapshot"]).is_file(), row["path"]
        line = f"  {row['path']}  {row['outcome']}" + (
            f"  {row['reason']}" if row["reason"] else ""
        )
        assert line + ("  (already the original)" if row["path"] in already else "") in shown
        if row["outcome"] == "skipped":
            assert f"      original  {Path(_evidence(state), row['snapshot'])}" in shown


@parametrised
def test_a_command_the_run_did_not_start_left_nothing_behind(state: dict[str, Any]) -> None:
    """A skipped baseline leaves no trace in the record, so the command's marker file is checked."""
    expected = state["spec"].get("started")
    if expected is None:
        return
    assert state["started"] is expected


@parametrised
def test_a_dry_run_prints_its_diff_after_the_file_lines_and_names_the_file(
    state: dict[str, Any],
) -> None:
    spec = state["spec"]
    if spec["argv"][0] != "fix":
        return
    shown = state["result"].stdout.splitlines()
    patch = state["after"]["patch.diff"].decode("utf-8").splitlines()
    total = spec.get("diff_lines")
    if not total:
        assert not [line for line in shown if line.startswith(("diff --git ", "Diff: "))]
        if total == 0:
            assert patch == []
        return
    assert len(patch) == total
    cap, patch_file = KEY["diff"]["lines"], Path(_evidence(state), "patch.diff")
    last = KEY["diff"]["whole" if total <= cap else "cut"]
    printed = patch[:cap]
    for held, shown_as in KEY["diff"]["redacted"].items():
        assert any(held in line for line in printed), f"{held} is not in the printed part"
        printed = [line.replace(held, shown_as) for line in printed]
    block = [*printed, last.format(patch=patch_file, lines=cap, total=total)]
    start = shown.index(block[0])
    assert shown[start : start + len(block)] == block
    planned = json.loads(state["after"]["plan.json"])["files"]
    assert shown[start - 1] == ""
    assert shown[start - 2].startswith(f"  {planned[-1]['path']}  (")


def _evidence(state: dict[str, Any]) -> str:
    """The run folder as the `Evidence:` line spells it: under `--repo` as the harness typed it."""
    return str(state["work"] / ".obelize" / "runs" / state["folder"].name)


@parametrised
def test_the_evidence_line_names_a_folder_that_opens_from_here(state: dict[str, Any]) -> None:
    named = Path(_evidence(state), "undo.json" if state["spec"]["argv"][0] == "undo" else "")
    assert f"Evidence: {named}" in state["result"].stdout.splitlines()
    assert Path(named).exists()


@parametrised
def test_no_line_obelize_prints_is_markdown(state: dict[str, Any]) -> None:
    """A terminal shows a backtick as one; a line of the quoted diff is the user's own code."""
    quoted = set(state["after"].get("patch.diff", b"").decode("utf-8").splitlines())
    shown = state["result"].output.splitlines()
    assert [line for line in shown if "`" in line and line not in quoted] == []


@parametrised
def test_a_fix_run_ends_with_the_step_after_it(state: dict[str, Any]) -> None:
    spec = state["spec"]
    if spec["argv"][0] != "fix":
        return
    shown = state["result"].stdout.splitlines()
    if spec["next"] is None:
        assert not [line for line in shown if line.startswith("Next:")]
        return
    assert shown[-1] == spec["next"].format(
        run=state["folder"].name,
        repo=copied(state["work"]),
        tests=copied("<project python> -m pytest -q"),
        report=Path(_evidence(state), "REPORT.md"),
    )


@parametrised
def test_the_verification_index_is_the_one_the_record_holds(state: dict[str, Any]) -> None:
    """`verify/verify.json` mirrors `run.json`'s `verify`; a re-verification must replace both."""
    mirror = state["after"].get("verify/verify.json")
    if mirror is None:
        return
    assert json.loads(mirror) == state["run"]["verify"]
