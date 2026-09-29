"""Whole runs over small git repositories, graded on the bytes left on disk and the tree state.

`tests/unit/test_fsutil.py` covers what no repository can pose: a path or directory that became a
symlink after planning, and a rename failing halfway.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from obelize import fsutil
from obelize.models import Config
from obelize.packs import loader
from obelize.scan import runner, walker
from obelize.transforms import codemod

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "apply"
REPOSITORY = Path(__file__).resolve().parents[2]
BASIC = REPOSITORY / "tests" / "fixtures" / "scan" / "basic"
ENCODING = REPOSITORY / "tests" / "fixtures" / "scan" / "encoding"
BUNDLED = loader.load("gemini/google-generativeai-to-google-genai")
SPEC = loader.to_scan_spec(BUNDLED)
KEY: dict[str, Any] = yaml.safe_load((ROOT / "answers.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["case"]: case for case in KEY["cases"]}

# The two answer-key spellings used across the corpus.
SUFFIXES = (".after", ".after.py")

# A generator and a scan key: in a fixture directory, but not inputs.
NOT_INPUT = ("_build.py", "ground_truth.yaml")


def is_key(name: str) -> bool:
    return name.endswith(SUFFIXES)


def answer(case: Path, name: str) -> Path:
    """The key for `name`, in whichever of the two spellings it uses."""
    if name.endswith(".py"):
        return case / (name.removesuffix(".py") + ".after.py")
    return case / (name + ".after")


def inputs(source: Path) -> list[Path]:
    """Non-key files outside `__pycache__` and dot-directories, so stray bytecode is not copied."""
    return [
        path
        for path in sorted(source.rglob("*"))
        if path.is_file()
        and not is_key(path.name)
        and path.name not in NOT_INPUT
        and not any(
            part == "__pycache__" or part.startswith(".")
            for part in path.relative_to(source).parts[:-1]
        )
    ]


def test_bytecode_and_hidden_directories_are_not_inputs(tmp_path: Path) -> None:
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "note.txt").write_text("x", encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    assert inputs(tmp_path) == [tmp_path / "app.py"]


def copied(source: Path, destination: Path) -> None:
    for path in inputs(source):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def git(root: Path, *arguments: str) -> None:
    """`commit.gpgsign` is off, or a globally signing developer's run stops at a key prompt."""
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *arguments],
        check=True,
        capture_output=True,
    )


def prepare(work: Path, root: Path, state: dict[str, Any]) -> None:
    """Commit first, so what the key calls dirty or untracked became so after a clean tree existed.
    The repository is at `work`; `root`, what `--repo` names, may be a subdirectory."""
    if state.get("init"):
        git(work, "init", "-q", "-b", "work")
        git(work, "config", "user.name", "obelize tests")
        git(work, "config", "user.email", "tests@obelize.invalid")
        left_out = set(state.get("never_added") or [])
        git(
            work,
            "add",
            *(
                path.relative_to(work).as_posix()
                for path in sorted(root.iterdir())
                if path.is_file() and path.name not in left_out
            ),
        )
        git(work, "commit", "-q", "-m", "the tree before obelize saw it")
    for name, text in (state.get("untracked") or {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    for name, text in (state.get("appended") or {}).items():
        with (root / name).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    for name in state.get("staged") or []:
        git(root, "add", name)


def snapshot(work: Path) -> dict[str, bytes]:
    """Every file outside `.git/`, by relative path."""
    return {
        str(path.relative_to(work).as_posix()): path.read_bytes()
        for path in sorted(work.rglob("*"))
        if path.is_file() and ".git/" not in str(path.relative_to(work).as_posix())
    }


def plan(work: Path, config: Config | None = None) -> codemod.Run:
    """From the walk to the last manifest edit, writing nothing."""
    config = config or Config()
    scan = runner.scan(work, config, SPEC, jobs=1)
    selection = walker.walk(work, config)
    wanted = {result.path for result in scan.results} | set(selection.manifests)
    sources = {name: (work / name).read_bytes() for name in sorted(wanted)}
    return codemod.run(scan, sources, BUNDLED.pack, SPEC)


def changes(run: codemod.Run) -> list[fsutil.Change]:
    return [fsutil.Change(path=row.path, before=row.before, after=row.after) for row in run.written]


def migrate(work: Path, *, allow_dirty: bool = False, config: Config | None = None) -> fsutil.Apply:
    return fsutil.apply(work, changes(plan(work, config)), allow_dirty=allow_dirty)


@pytest.fixture(scope="module")
def corpora(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """Every case built into its git state, snapshotted, and applied once."""
    built: dict[str, dict[str, Any]] = {}
    for name in sorted(CASES):
        work = tmp_path_factory.mktemp(name)
        state = CASES[name].get("git") or {}
        root = work / state.get("subdirectory", "")
        root.mkdir(parents=True, exist_ok=True)
        copied(ROOT / name, root)
        prepare(work, root, state)
        before = snapshot(root)
        applied = migrate(root, allow_dirty=bool(CASES[name].get("allow_dirty")))
        built[name] = {"root": root, "before": before, "applied": applied}
    return built


def test_the_key_grades_every_case_and_every_case_has_a_row() -> None:
    on_disk = {path.name for path in ROOT.iterdir() if path.is_dir()}
    assert on_disk == set(CASES), sorted(on_disk ^ set(CASES))


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_key_grades_every_file_and_every_file_has_a_row(name: str) -> None:
    case = ROOT / name
    found = {str(path.relative_to(case).as_posix()) for path in inputs(case)}
    graded = {row["file"] for row in CASES[name]["files"]}
    assert found == graded, sorted(found ^ graded)
    keys = {
        str(path.relative_to(case).as_posix()).removesuffix(".after").replace(".after.py", ".py")
        for path in sorted(case.rglob("*"))
        if path.is_file() and is_key(path.name)
    }
    assert keys == {row["file"] for row in CASES[name]["files"] if row["after"] == "present"}


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_tree_decided_what_the_key_says_it_decided(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    """`dirty`, `refused` and so `blocked`: TM-8's whole truth table."""
    applied: fsutil.Apply = corpora[name]["applied"]
    expected = CASES[name]
    assert list(applied.dirty) == expected["dirty"]
    assert [(row.path, row.reason) for row in applied.refused] == [
        (row["path"], row["reason"]) for row in expected["refused"]
    ]
    assert applied.blocked is bool(expected["dirty"] or expected["refused"])


@pytest.mark.parametrize("name", sorted(CASES))
def test_what_a_run_writes_is_what_the_key_names(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    applied: fsutil.Apply = corpora[name]["applied"]
    assert [row.path for row in applied.written] == CASES[name]["written"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_file_on_the_disk_is_what_the_key_says(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    """A refusal owes "changed nothing", not "wrote nothing", so every file in the tree counts."""
    work: Path = corpora[name]["root"]
    before: dict[str, bytes] = corpora[name]["before"]
    for row in CASES[name]["files"]:
        produced = (work / row["file"]).read_bytes()
        expected = (
            answer(ROOT / name, row["file"]).read_bytes()
            if row["after"] == "present"
            else before[row["file"]]
        )
        assert produced == expected, row["file"]
    untouched = {
        path: data for path, data in before.items() if path not in set(CASES[name]["written"])
    }
    assert {path: (work / path).read_bytes() for path in untouched} == untouched


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_written_file_records_the_two_hashes(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    """`undo` and `verify` read these back."""
    work: Path = corpora[name]["root"]
    before: dict[str, bytes] = corpora[name]["before"]
    for row in corpora[name]["applied"].written:
        assert row.before_sha256 == fsutil.sha256(before[row.path])
        assert row.after_sha256 == fsutil.sha256((work / row.path).read_bytes())
        assert row.before_sha256 != row.after_sha256


@pytest.mark.parametrize("name", sorted(CASES))
def test_no_temporary_file_is_left_behind(name: str, corpora: dict[str, dict[str, Any]]) -> None:
    work: Path = corpora[name]["root"]
    assert [str(path.relative_to(work)) for path in work.rglob(f"*{fsutil.TEMPORARY_SUFFIX}")] == []


@pytest.mark.parametrize("name", sorted(CASES))
def test_applying_twice_changes_nothing_the_second_time(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    """Refusing cases refuse again: the tree's answer does not depend on having been asked."""
    work: Path = corpora[name]["root"]
    state = snapshot(work)
    again = migrate(work, allow_dirty=bool(CASES[name].get("allow_dirty")))
    assert again.written == ()
    assert snapshot(work) == state


def test_the_basic_fixture_reaches_a_disk_as_its_phase_0_keys(tmp_path: Path) -> None:
    """Read back off the disk after temp file, fsync, chmod and rename, not from a return value."""
    copied(BASIC, tmp_path)
    applied = migrate(tmp_path)
    assert [row.path for row in applied.written] == ["app.py", "requirements.txt"]
    assert (tmp_path / "app.py").read_bytes() == (BASIC / "app.after.py").read_bytes()
    assert (tmp_path / "requirements.txt").read_bytes() == (
        BASIC / "requirements.after.txt"
    ).read_bytes()


def test_every_encoding_fixture_survives_a_read_modify_write(tmp_path: Path) -> None:
    """Four match their `.after.py` keys; `bare_cr.py` (libcst loses a byte) and the two unparsed
    files stay untouched. One repository each: the unparsed two import the SDK without
    `configure` and would hold every other `configure` back (ADR-031 D11)."""
    migrated = {
        path.name.removesuffix(".after.py") + ".py"
        for path in ENCODING.iterdir()
        if path.name.endswith(".after.py")
    }
    for path in inputs(ENCODING):
        work = tmp_path / path.stem
        work.mkdir()
        (work / path.name).write_bytes(path.read_bytes())
        applied = migrate(work)
        written = [path.name] if path.name in migrated else []
        assert [row.path for row in applied.written] == written, path.name
        expected = answer(ENCODING, path.name) if path.name in migrated else path
        assert (work / path.name).read_bytes() == expected.read_bytes(), path.name
