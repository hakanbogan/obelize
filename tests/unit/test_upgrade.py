"""`obelize upgrade`: one dependency to a newer release, with the pack that exists or one made."""

from __future__ import annotations

import sys
import sysconfig
from typing import TYPE_CHECKING

import pytest
import typer
from packaging.version import Version
from typer.testing import CliRunner, Result

import fakeindex
from obelize import cli, index
from obelize import upgrade as upgrading
from obelize.cli import app
from obelize.packs import loader
from obelize.packtools import synth
from support import committed, git

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()
PYTHON = f"{sys.version_info.major}.{sys.version_info.minor}"

V1 = "def old_greet(name):\n    return name\n\ndef removed_fn(x):\n    return x\n"
V15 = (
    "import warnings\n\ndef greet(name):\n    return name\n\n"
    "def old_greet(name):\n"
    "    warnings.warn('old_greet is deprecated, use greet instead', DeprecationWarning)\n"
    "    return greet(name)\n\ndef removed_fn(x):\n    return x\n"
)
V2 = "def greet(name):\n    return name\n"
# Renamed like acme-kit, but the new name does something else, which only a test would show.
SHOUT_V2 = "def greet(name):\n    return name.upper()\n"
APP = "import acme_kit\n\n\ndef run(name):\n    return acme_kit.old_greet(name)\n"
PDF = "import PyPDF2\n\n\ndef pages(path):\n    return PyPDF2.PdfReader(path).pages\n"


@pytest.fixture(scope="module")
def served() -> Iterator[fakeindex.FakeIndex]:
    for found in fakeindex.FakeIndex().serve():
        for version, source in (("1.0", V1), ("1.5", V15), ("2.0", V2)):
            found.add("acme-kit", version, {"__init__.py": source}, module="acme_kit")
        # Only a record that pytest is installed: the module comes from this interpreter.
        found.add("pytest", "0", {}, module="")
        for version, source in (("1.0", V1), ("1.5", V15), ("2.0", SHOUT_V2)):
            found.add("shout-kit", version, {"__init__.py": source}, module="shout_kit")
        found.add("pypdf2", "3.0.1", {"__init__.py": "x = 1\n"}, module="PyPDF2")
        found.add("pypdf", "6.19.0", {"__init__.py": "x = 1\n"})
        yield found


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, served: fakeindex.FakeIndex) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("OBELIZE_INDEX_URL", served.url)
    monkeypatch.delenv("OBELIZE_OFFLINE", raising=False)
    return tmp_path


def repo(home: Path, **files: str) -> Path:
    return committed(home / "repo", {name.replace("__", "."): body for name, body in files.items()})


def test_a_library_with_no_pack_is_planned_with_a_pack_made_from_its_two_releases(
    home: Path,
) -> None:
    root = repo(home, app__py=APP, requirements__txt="acme-kit==1.0\n")
    result = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert (
        "Moving acme-kit 1.0 to 2.0. Made a pack from the public API of acme-kit 1.0 and 2.0"
        in result.output
    )
    assert "acme_kit.old_greet" in result.output
    assert (home / "cache" / "obelize" / "packs").is_dir()
    assert "acme_kit.greet" in next(root.glob(".obelize/runs/*/patch.diff")).read_text()
    assert (root / "app.py").read_text() == APP


def test_the_pack_made_is_kept_and_a_second_run_asks_the_index_for_no_release(
    home: Path, served: fakeindex.FakeIndex
) -> None:
    root = repo(home, app__py=APP, requirements__txt="acme-kit==1.0\n")
    runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root)])
    served.asked.clear()
    again = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root), "--offline"])
    assert again.exit_code == 0, again.output
    assert "Using the pack made from these two releases before." in again.output
    assert served.asked == []


def test_a_distribution_a_bundled_pack_migrates_uses_it(home: Path) -> None:
    root = repo(home, pdf__py=PDF, requirements__txt="PyPDF2==3.0.1\n")
    result = runner.invoke(app, ["upgrade", "PyPDF2", "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "Using the pack py-pdf/pypdf2-to-pypdf." in result.output


def test_a_release_the_person_names_is_one_the_pack_must_reach(home: Path) -> None:
    root = repo(home, pdf__py=PDF, requirements__txt="PyPDF2==3.0.1\n")
    result = runner.invoke(app, ["upgrade", "PyPDF2", "--repo", str(root), "--to", "3.0.1"])
    assert result.exit_code == 2
    assert "nothing to synthesize" in result.output


def test_a_dependency_the_manifests_do_not_name_needs_the_release_it_is_written_for(
    home: Path,
) -> None:
    root = repo(home, app__py=APP, requirements__txt="requests\n")
    refused = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root)])
    assert refused.exit_code == 2
    assert "pass --from" in refused.output
    named = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root), "--from", "1.0"])
    assert named.exit_code == 0, named.output


@pytest.mark.parametrize(
    ("arguments", "code", "message"),
    [
        (["nothing-here", "--from", "1.0"], 2, ""),
        (["acme-kit", "--from", "banana"], 2, "is not a version"),
        (["acme-kit", "--from", "1.0", "--to", "banana"], 2, "is not a version"),
        (["acme-kit", "--from", "1.0", "--offline"], 6, "not in the cache"),
    ],
)
def test_a_request_the_index_cannot_meet_exits_with_the_reason(
    home: Path, arguments: list[str], code: int, message: str
) -> None:
    root = repo(home, requirements__txt="acme-kit==1.0\n")
    result = runner.invoke(app, ["upgrade", *arguments, "--repo", str(root)])
    assert result.exit_code == code
    assert message in result.output


def test_a_pack_obelize_made_and_cannot_stand_behind_is_a_defect(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> object:
        raise synth.SynthDefectError("the pack made fails pack test")

    monkeypatch.setattr(synth, "make", refuse)
    root = repo(home, requirements__txt="acme-kit==1.0\n")
    result = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root)])
    assert result.exit_code == 1
    assert "fails pack test" in result.output


def test_a_repository_that_is_not_a_directory_exits_two(home: Path) -> None:
    result = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(home / "nothing")])
    assert result.exit_code == 2


# Applying, after a trial.

TESTS = (
    "import app\n\n\ndef test_hello():\n    assert app.hello('x') == 'x'\n\n\n"
    "def test_again():\n    assert app.hello('y') == 'y'\n"
)
HELLO = "import acme_kit\n\n\ndef hello(name):\n    return acme_kit.old_greet(name)\n"


@pytest.fixture
def trial(home: Path, served: fakeindex.FakeIndex, monkeypatch: pytest.MonkeyPatch) -> Path:
    """uv installs from the fake index; pytest comes from the interpreter that runs these tests."""
    monkeypatch.setenv("UV_DEFAULT_INDEX", served.url)
    monkeypatch.setenv("UV_CACHE_DIR", str(home / "uv"))
    monkeypatch.setenv("PYTHONPATH", sysconfig.get_paths()["purelib"])
    monkeypatch.delenv("CI", raising=False)
    return home


def tried(root: Path, *extra: str) -> Result:
    return runner.invoke(
        app,
        ["upgrade", "acme-kit", "--repo", str(root), "--python", PYTHON, "--apply", *extra],
    )


def test_a_move_whose_tests_pass_is_tried_in_a_copy_and_then_written(trial: Path) -> None:
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    result = tried(root, "--yes")
    assert result.exit_code == 0, result.output
    assert "Trial of acme-kit 1.0 to acme-kit==2.0: pass" in result.output
    assert "2 test(s) passed before, 0 broke" in result.output
    assert "acme_kit.greet(name)" in (root / "app.py").read_text()
    assert (root / "requirements.txt").read_text() != "acme-kit==1.0\n"
    folder = next((root / ".obelize" / "trials").iterdir())
    assert (folder / "trial.json").is_file()


def test_a_move_that_breaks_a_test_is_not_written(trial: Path) -> None:
    hello = HELLO.replace("acme_kit", "shout_kit")
    root = repo(trial, app__py=hello, test_app__py=TESTS, requirements__txt="shout-kit==1.0\n")
    result = runner.invoke(
        app,
        ["upgrade", "shout-kit", "--repo", str(root), "--python", PYTHON, "--apply", "--yes"],
    )
    assert result.exit_code == 3, result.output
    assert "broke: test_app::test_hello" in result.output
    assert (root / "app.py").read_text() == hello
    assert (root / "requirements.txt").read_text() == "shout-kit==1.0\n"


def test_a_repository_with_no_tests_is_not_written_by_a_trial(trial: Path) -> None:
    root = repo(trial, app__py=HELLO, requirements__txt="acme-kit==1.0\n")
    result = tried(root, "--yes")
    assert result.exit_code == 6
    assert "No tests were found" in result.output
    assert (root / "app.py").read_text() == HELLO


@pytest.mark.parametrize("ci", [False, True])
def test_a_trial_is_not_run_without_the_persons_yes(
    trial: Path, monkeypatch: pytest.MonkeyPatch, ci: bool
) -> None:
    if ci:
        monkeypatch.setenv("CI", "true")
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    result = tried(root)
    assert result.exit_code == 2
    assert "Pass --yes to agree." in result.output
    assert not (root / ".obelize" / "trials").exists()


def test_a_trial_that_cannot_make_its_environments_exits_six(trial: Path) -> None:
    root = repo(trial, app__py=HELLO, test_app__py=TESTS)
    result = tried(root, "--from", "1.0", "--yes")
    assert result.exit_code == 6
    assert "no way to install" in result.output


def test_a_dirty_tree_is_refused_before_the_trial_begins(trial: Path) -> None:
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    (root / "app.py").write_text(HELLO + "# edited\n")
    result = tried(root, "--yes")
    assert result.exit_code == 5
    assert "uncommitted changes" in result.output
    assert not (root / ".obelize" / "trials").exists()


def test_a_write_that_ends_for_another_reason_keeps_its_exit_code(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def review(**_found: object) -> None:
        raise typer.Exit(4)

    monkeypatch.setattr(cli, "fix", review)
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    assert tried(root, "--yes").exit_code == 4


# Which pack, and what the environment of the release moved to holds.


def project(name: str) -> index.Project:
    return index.Project(name, ())


@pytest.mark.parametrize(
    ("name", "now", "target", "targeted", "install", "remove"),
    [
        ("pypdf2", "3.0.1", "3.0.1", False, "pypdf>=6.19", "pypdf2"),
        ("openai", "0.28.1", "3.35.1", False, "openai>=1.109.1", None),
        ("openai", "0.28.1", "1.109.1", True, "openai==1.109.1", None),
    ],
)
def test_the_environment_of_a_known_pack_holds_the_distribution_and_range_the_pack_says(
    name: str, now: str, target: str, targeted: bool, install: str, remove: str | None
) -> None:
    known = [loader.load(reference) for reference in loader.known()]
    chosen = upgrading.choose(
        None,  # type: ignore[arg-type]
        project(name),
        Version(now),
        Version(target),
        targeted=targeted,
        module=None,
        known=known,
        kept=None,  # type: ignore[arg-type]
    )
    assert (chosen.install, chosen.remove) == (install, remove)


def test_a_move_whose_tests_pass_can_be_committed_to_a_branch_instead_of_the_tree(
    trial: Path,
) -> None:
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    result = tried(root, "--yes", "--branch")
    assert result.exit_code == 0, result.output
    assert (
        "on the new branch obelize/upgrade-acme-kit-2.0; the working tree is unchanged"
        in result.output
    )
    assert (root / "app.py").read_text() == HELLO
    assert (
        git(root, "show", "obelize/upgrade-acme-kit-2.0:app.py").stdout.decode().count("greet(")
        == 1
    )
    said = git(root, "log", "-1", "--format=%B", "obelize/upgrade-acme-kit-2.0").stdout.decode()
    assert said.startswith("Upgrade acme-kit 1.0 to acme-kit==2.0\n")
    assert "Obelize-Trial: " in said


def test_a_branch_the_person_names_is_the_one_made_and_one_that_exists_is_refused(
    trial: Path,
) -> None:
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    made = tried(root, "--yes", "--branch-name", "chore/acme")
    assert made.exit_code == 0, made.output
    assert "chore/acme" in git(root, "branch").stdout.decode()
    again = tried(root, "--yes", "--branch-name", "chore/acme")
    assert again.exit_code == 2
    assert "exists already" in again.output


def test_a_branch_needs_a_trial(trial: Path) -> None:
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    result = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root), "--branch"])
    assert result.exit_code == 2
    assert "needs --apply" in result.output
