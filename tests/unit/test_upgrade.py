"""`obelize upgrade`: one dependency to a newer release, with the pack that exists or one made."""

from __future__ import annotations

import json
import sys
import sysconfig
from typing import TYPE_CHECKING

import pytest
import typer
from packaging.version import Version
from typer.testing import CliRunner, Result

import fakeindex
from obelize import cli, index, libdiff
from obelize import upgrade as upgrading
from obelize.cli import app
from obelize.models import EditProposal
from obelize.net import Fetcher
from obelize.packs import loader
from obelize.packtools import synth
from obelize.providers import agent_cli, base
from obelize.trial import copy
from obelize.trial import run as trying
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


def repo2(home: Path, name: str, code: str) -> Path:
    return committed(home / name, {"app.py": code, "requirements.txt": "acme-kit==1.0\n"})


def too_large_unless_scoped(monkeypatch: pytest.MonkeyPatch) -> list[synth.Request]:
    """`synth.make` as it is, except that a pack for every change is more than a pack holds."""
    real = synth.make
    whole: list[synth.Request] = []

    def make(directory: Path, request: synth.Request, *rest: object) -> object:
        if request.scope is None:
            whole.append(request)
            raise synth.SynthTooLargeError("acme-kit changed 2 names, more than a pack holds.")
        return real(directory, request, *rest)  # type: ignore[arg-type]

    monkeypatch.setattr(synth, "make", make)
    return whole


def test_a_library_that_changed_too_much_gets_a_pack_for_the_names_the_repository_uses(
    home: Path, served: fakeindex.FakeIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    whole = too_large_unless_scoped(monkeypatch)
    root = repo(home, app__py=APP, requirements__txt="acme-kit==1.0\n")
    result = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "more than a pack holds. It flags the 1 name(s) this repository uses." in result.output
    assert "acme_kit.greet" in next(root.glob(".obelize/runs/*/patch.diff")).read_text()
    assert len(whole) == 1
    kept = home / "cache" / "obelize" / "packs"
    assert list(kept.rglob("*.too-large"))
    served.asked.clear()
    again = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root), "--offline"])
    assert again.exit_code == 0, again.output
    assert "Using the pack made for the names this repository uses before." in again.output
    assert served.asked == []
    assert len(whole) == 1
    star = repo2(home, "star", "from acme_kit import *\n")
    other = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(star)])
    assert other.exit_code == 2
    assert len(whole) == 2


def test_a_library_too_large_to_flag_whole_needs_a_repository_that_can_be_read(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    too_large_unless_scoped(monkeypatch)
    star = repo(home, app__py="from acme_kit import *\n", requirements__txt="acme-kit==1.0\n")
    refused = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(star)])
    assert refused.exit_code == 2
    assert "more than a pack holds" in refused.output
    plain = committed(
        home / "plain", {"app.py": "import acme_kit\n", "requirements.txt": "acme-kit==1.0\n"}
    )
    nothing = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(plain)])
    assert nothing.exit_code == 2
    assert "nothing to flag" in nothing.output


def test_upgrade_with_no_dependency_lists_those_behind_and_asks_where_a_person_can_be(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo(home, app__py=APP, requirements__txt="acme-kit==1.0\n")
    listed = runner.invoke(app, ["upgrade", "--repo", str(root)])
    assert listed.exit_code == 2
    assert " 1 acme-kit" in listed.output
    assert "Name one of them: obelize upgrade <distribution>" in listed.output
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    for answer in ("1\n", "acme-kit\n", "\n"):
        picked = runner.invoke(app, ["upgrade", "--repo", str(root)], input=answer)
        assert picked.exit_code == 0, picked.output
        assert "Moving acme-kit 1.0 to 2.0." in picked.output
    wrong = runner.invoke(app, ["upgrade", "--repo", str(root)], input="3\n")
    assert wrong.exit_code == 2
    assert "'3' is none of the 1 listed" in wrong.output


def test_upgrade_with_no_dependency_and_no_index_to_ask_exits_six(home: Path) -> None:
    root = repo(home, app__py=APP, requirements__txt="acme-kit==1.0\n")
    result = runner.invoke(app, ["upgrade", "--repo", str(root), "--offline"])
    assert result.exit_code == 6
    assert "The index could not be reached for any dependency." in result.output


def test_upgrade_with_no_dependency_behind_says_so(home: Path) -> None:
    root = repo(home, app__py=APP, requirements__txt="acme-kit==2.0\n")
    result = runner.invoke(app, ["upgrade", "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "none behind a major release that can be moved" in result.output


def test_a_distribution_a_bundled_pack_migrates_uses_it(home: Path) -> None:
    root = repo(home, pdf__py=PDF, requirements__txt="PyPDF2==3.0.1\n")
    result = runner.invoke(app, ["upgrade", "PyPDF2", "--repo", str(root)])
    assert result.exit_code == 0, result.output
    assert "Using the pack py-pdf/pypdf2-to-pypdf." in result.output
    assert "Moving pypdf2 3.0.1 to pypdf" in result.output


def test_a_module_the_python_or_setuptools_holds_is_no_dependency_to_upgrade(home: Path) -> None:
    root = repo(home, app__py="import pkg_resources\n", requirements__txt="requests\n")
    result = runner.invoke(app, ["upgrade", "pkg_resources", "--repo", str(root)])
    assert result.exit_code == 2
    assert "is a module of the Python or of setuptools" in result.output
    assert "obelize fix --pack setuptools/pkg-resources-to-importlib" in result.output


def test_a_distribution_of_that_name_the_manifests_declare_is_upgraded_as_any_other(
    home: Path,
) -> None:
    root = repo(home, app__py=APP, requirements__txt="datetime==1.0\n")
    result = runner.invoke(app, ["upgrade", "datetime", "--repo", str(root)])
    assert "is a module of the Python" not in result.output


def test_a_pack_whose_new_side_is_a_python_is_never_chosen_to_move_a_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is skipped, so the search goes on to the two releases, which this stops at."""
    known = [loader.load("setuptools/pkg-resources-to-importlib")]

    def compare(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("reached the two releases")

    monkeypatch.setattr(libdiff, "compare", compare)
    with pytest.raises(RuntimeError, match="reached the two releases"):
        upgrading.choose(
            Fetcher(index="http://127.0.0.1:1/simple"),
            index.Project(name="setuptools", files=()),
            Version("81.0.0"),
            Version("84.2.1"),
            targeted=False,
            module=None,
            known=known,
            kept=tmp_path,
        )


def test_the_module_a_pack_of_the_python_matches_names_that_pack() -> None:
    known = [loader.load(reference) for reference in loader.known()]
    assert upgrading.runtime_pack(known, "pkg_resources") == "setuptools/pkg-resources-to-importlib"
    assert upgrading.runtime_pack(known, "datetime") == "python/datetime-utcnow"
    assert upgrading.runtime_pack(known, "asyncore") == "python/removed-stdlib-modules"
    assert upgrading.runtime_pack(known, "PyPDF2") is None
    assert upgrading.runtime_pack(known, "setuptools") is None


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


def test_a_floor_without_a_pin_is_run_on_the_floor_before_the_move(trial: Path) -> None:
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit>=1.0\n")
    result = tried(root, "--yes")
    assert result.exit_code == 0, result.output
    folder = next((root / ".obelize" / "trials").iterdir())
    assert "acme-kit==1.0" in (folder / "old.txt").read_text()
    assert "acme-kit==2.0" in (folder / "new.txt").read_text()


def test_a_repository_named_by_a_relative_path_keeps_its_evidence(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pytest reads a relative `--junitxml` from the copy, so the evidence path must not be one."""
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    monkeypatch.chdir(root.parent)
    result = runner.invoke(
        app,
        ["upgrade", "acme-kit", "--repo", "repo", "--python", PYTHON, "--apply", "--yes"],
    )
    assert result.exit_code == 0, result.output
    folder = next((root / ".obelize" / "trials").iterdir())
    assert (folder / "before" / "1.junit.xml").is_file()
    assert (folder / "after" / "1.junit.xml").is_file()


def test_a_file_the_tests_leave_in_the_copy_is_not_part_of_the_move(trial: Path) -> None:
    leaving = TESTS + "\n\ndef test_leaves():\n    open('leftover.txt', 'w').write('x')\n"
    root = repo(trial, app__py=HELLO, test_app__py=leaving, requirements__txt="acme-kit==1.0\n")
    result = tried(root, "--yes", "--branch")
    assert result.exit_code == 0, result.output
    shown = git(root, "show", "--stat", "--format=", "obelize/upgrade-acme-kit-2.0").stdout.decode()
    assert "app.py" in shown
    assert "leftover.txt" not in shown


def test_a_module_that_does_not_import_does_not_hide_the_tests_of_the_others(trial: Path) -> None:
    root = repo(
        trial,
        app__py=HELLO,
        test_app__py=TESTS,
        test_other__py="import nothere\n",
        requirements__txt="acme-kit==1.0\n",
    )
    result = tried(root, "--yes")
    assert result.exit_code == 0, result.output
    assert "2 test(s) passed before, 0 broke" in result.output


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


def test_the_time_the_tests_may_take_reaches_the_trial(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []

    def stop(plan: trying.Plan) -> trying.Trial:
        seen.append(plan.timeout_s)
        raise copy.CopyError("stopped here")

    monkeypatch.setattr(trying, "run", stop)
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    assert tried(root, "--yes", "--timeout", "7").exit_code == 6
    assert tried(root, "--yes").exit_code == 6
    assert seen == [7, trying.TEST_TIMEOUT_S]


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


# A model for the places a pack only flags.

GONE = "import acme_kit\n\n\ndef gone(x):\n    return acme_kit.removed_fn(x)\n"
WITH_GONE = TESTS + "\n\ndef test_gone():\n    import other\n\n    assert other.gone(1) == 1\n"


class Agent:
    """A model that answers the questions in turn, each by replacing one line, or by nothing."""

    program = "claude"

    def __init__(self, replacement: str | None, *later: tuple[str, str]) -> None:
        self.answers = [("    return acme_kit.removed_fn(x)", replacement), *later]
        self.asked: list[base.Consultation] = []

    def request(self, consultation: base.Consultation) -> bytes:
        return b""

    def propose(self, consultation: base.Consultation) -> base.Reply:
        self.asked.append(consultation)
        index = len(self.asked) - 1
        replaces, replacement = self.answers[index] if index < len(self.answers) else ("", None)
        if replacement is None:
            return base.Reply(None)
        line = consultation.line
        proposal = EditProposal(
            path=consultation.context.path,
            start_line=line,
            end_line=line,
            symbol=consultation.symbol or "",
            replaces=replaces,
            replacement=replacement,
            rationale="removed_fn only returned its argument.",
        )
        return base.Reply(proposal, 11, 7)


class Unchanged(Agent):
    """A model that says every place it is asked about needs no edit."""

    def __init__(self) -> None:
        super().__init__(None)

    def propose(self, consultation: base.Consultation) -> base.Reply:
        self.asked.append(consultation)
        return base.Reply(None, 5, 3, "Nothing here is called by anything that changed.")


def agent_world(trial: Path, monkeypatch: pytest.MonkeyPatch, model: Agent) -> Path:
    monkeypatch.setattr(agent_cli, "build", lambda *_args, **_kwargs: model)
    return repo(
        trial,
        app__py=HELLO,
        other__py=GONE,
        test_app__py=WITH_GONE,
        requirements__txt="acme-kit==1.0\n",
    )


def test_a_place_the_pack_flags_is_put_to_the_agent_and_the_move_it_allows_is_committed(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = Agent("    return x")
    root = agent_world(trial, monkeypatch, model)
    result = tried(root, "--yes", "--branch", "--agent", "claude_code")
    assert result.exit_code == 0, result.output
    assert "will be put to claude, one place at a time" in result.output
    assert (
        "The model was asked about 1 place(s); 1 file(s) were edited, 0 place(s) need no edit, "
        "0 place(s) are left" in result.output
    )
    assert model.asked[0].bail == "flag_only_surface"
    assert "Removed in acme-kit 2.0" in (model.asked[0].note or "")
    name = "obelize/upgrade-acme-kit-2.0"
    assert git(root, "show", f"{name}:other.py").stdout.decode().endswith("    return x\n")
    assert "acme_kit.greet(name)" in git(root, "show", f"{name}:app.py").stdout.decode()
    assert git(root, "show", f"{name}:requirements.txt").stdout.decode() != "acme-kit==1.0\n"
    said = git(root, "log", "-1", "--format=%B", name).stdout.decode()
    assert "A model edited other.py: read those lines first." in said
    assert (root / "other.py").read_text() == GONE
    folder = next((root / ".obelize" / "trials").iterdir())
    document = json.loads((folder / "trial.json").read_text())
    assert document["model"]["rounds"][0]["name"] == "resolve"
    assert document["model"]["rounds"][0]["places"][0]["outcome"] == "edited"
    assert (document["model"]["tokens_in"], document["model"]["tokens_out"]) == (11, 7)


def test_places_the_model_leaves_alone_leave_the_move_unwritten(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = agent_world(trial, monkeypatch, Agent(None))
    result = tried(root, "--yes", "--branch", "--agent", "claude_code")
    assert result.exit_code == 6
    assert "unresolved" in result.output
    assert "Places the pack flags are left" in result.output
    assert "obelize/upgrade-acme-kit-2.0" not in git(root, "branch").stdout.decode()


def test_the_user_may_name_the_agent_in_the_config_file_instead_of_the_flag(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (trial / "config" / "obelize").mkdir(parents=True)
    (trial / "config" / "obelize" / "config.yml").write_text(
        "agent:\n  backend: claude_code\n  model: sonnet\n"
    )
    root = agent_world(trial, monkeypatch, Agent("    return x"))
    result = tried(root, "--yes", "--branch")
    assert result.exit_code == 0, result.output


def test_an_agent_in_the_config_file_does_not_stop_a_dry_run_or_a_move_with_no_branch(
    trial: Path,
) -> None:
    (trial / "config" / "obelize").mkdir(parents=True)
    (trial / "config" / "obelize" / "config.yml").write_text("agent:\n  backend: claude_code\n")
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    dry = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root)])
    assert dry.exit_code == 0, dry.output
    assert "acme_kit.greet(name)" in dry.output
    written = tried(root, "--yes")
    assert written.exit_code == 0, written.output
    assert "acme_kit.greet(name)" in (root / "app.py").read_text()


def test_the_evidence_of_a_trial_is_ignored_by_git_like_a_run_folder(trial: Path) -> None:
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    result = tried(root, "--yes", "--branch")
    assert result.exit_code == 0, result.output
    assert (root / ".obelize" / ".gitignore").read_text() == "*\n"
    assert git(root, "status", "--porcelain").stdout.decode().strip() == ""


def test_offline_keeps_the_trials_installs_to_uvs_cache(trial: Path) -> None:
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    assert runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root)]).exit_code == 0
    result = tried(root, "--yes", "--offline")
    assert result.exit_code == 6, result.output
    assert "uv pip failed" in result.output
    assert (root / "app.py").read_text() == HELLO


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--agent", "claude_code"], "use --apply with --branch"),
        (["--agent", "claude_code", "--apply"], "use --apply with --branch"),
        (["--agent", "nonsense", "--apply", "--branch"], "--agent takes one of claude_code"),
    ],
)
def test_an_agent_without_a_branch_or_that_does_not_exist_is_refused(
    trial: Path, arguments: list[str], message: str
) -> None:
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    result = runner.invoke(app, ["upgrade", "acme-kit", "--repo", str(root), *arguments])
    assert result.exit_code == 2
    assert message in result.output


def test_an_agent_that_cannot_be_asked_ends_the_trial_before_it_begins(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> object:
        raise base.ProviderError("endpoint_unreachable", "claude is not on PATH")

    monkeypatch.setattr(agent_cli, "build", refuse)
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit==1.0\n")
    result = tried(root, "--yes", "--branch", "--agent", "claude_code")
    assert result.exit_code == 6
    assert "claude is not on PATH" in result.output


# A test the move broke, put to the model with its traceback.

BROKEN = ("    return acme_kit.removed_fn(x)", "    return x.missing")


def test_a_test_the_move_broke_is_put_to_the_agent_and_the_repair_is_committed(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = Agent("    return x.missing", ("    return x.missing", "    return x"))
    root = agent_world(trial, monkeypatch, model)
    result = tried(root, "--yes", "--branch", "--agent", "claude_code")
    assert result.exit_code == 0, result.output
    assert "Putting the 1 test(s) that broke to the model, round 1" in result.output
    note = model.asked[1].note or ""
    assert note.startswith("test_app::test_gone")
    assert "AttributeError" in note
    assert (model.asked[1].context.path, model.asked[1].line) == ("other.py", 5)
    name = "obelize/upgrade-acme-kit-2.0"
    assert git(root, "show", f"{name}:other.py").stdout.decode().endswith("    return x\n")
    folder = next((root / ".obelize" / "trials").iterdir())
    document = json.loads((folder / "trial.json").read_text())
    assert [one["name"] for one in document["model"]["rounds"]] == ["resolve", "repair-1"]
    assert document["model"]["tokens_in"] == 22
    assert (folder / "after-1").is_dir()


@pytest.mark.parametrize(
    ("arguments", "model", "asked"),
    [
        (["--max-rounds", "0"], Agent("    return x.missing"), 1),
        ([], Agent("    return x.missing"), 2),
        ([], Agent("    return x.missing", ("    return x.missing", "    return x.other")), 2),
    ],
    ids=["no rounds", "the model offers nothing", "no fewer tests broke"],
)
def test_a_test_that_stays_broken_leaves_the_move_unwritten(
    trial: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str], model: Agent, asked: int
) -> None:
    root = agent_world(trial, monkeypatch, model)
    result = tried(root, "--yes", "--branch", "--agent", "claude_code", *arguments)
    assert result.exit_code == 3, result.output
    assert len(model.asked) == asked
    assert "obelize/upgrade-acme-kit-2.0" not in git(root, "branch").stdout.decode()


def test_the_pin_follows_the_places_the_agent_moved_when_the_rules_wrote_nothing(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    only = "import other\n\n\ndef test_gone():\n    assert other.gone(1) == 1\n"
    model = Agent("    return x")
    monkeypatch.setattr(agent_cli, "build", lambda *_args, **_kwargs: model)
    root = repo(trial, other__py=GONE, test_other__py=only, requirements__txt="acme-kit==1.0\n")
    result = tried(root, "--yes", "--branch", "--agent", "claude_code")
    assert result.exit_code == 0, result.output
    name = "obelize/upgrade-acme-kit-2.0"
    assert git(root, "show", f"{name}:other.py").stdout.decode().endswith("    return x\n")
    assert git(root, "show", f"{name}:requirements.txt").stdout.decode() != "acme-kit==1.0\n"
    said = git(root, "log", "-1", "--format=%B", name).stdout.decode()
    assert "A model edited other.py: read those lines first." in said


def test_a_name_still_imported_in_a_file_the_agent_moved_does_not_hold_the_pin(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported = "import acme_kit\nfrom acme_kit import removed_fn\n\n\ndef gone(x):\n"
    imported += "    return acme_kit.removed_fn(x)\n"
    only = "import other\n\n\ndef test_gone():\n    assert other.gone(1) == 1\n"
    # The import of a removed name fails the test that loads it, and the repair round removes it.
    model = Agent("    return x", ("from acme_kit import removed_fn", "pass"))
    monkeypatch.setattr(agent_cli, "build", lambda *_args, **_kwargs: model)
    root = repo(trial, other__py=imported, test_other__py=only, requirements__txt="acme-kit==1.0\n")
    result = tried(root, "--yes", "--branch", "--agent", "claude_code")
    assert result.exit_code == 0, result.output
    name = "obelize/upgrade-acme-kit-2.0"
    assert git(root, "show", f"{name}:requirements.txt").stdout.decode() != "acme-kit==1.0\n"
    assert "could not be written" not in result.output


def test_a_place_the_agent_says_needs_no_edit_is_settled_and_only_the_tests_check_it(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = Unchanged()
    monkeypatch.setattr(agent_cli, "build", lambda *_args, **_kwargs: model)
    root = repo(
        trial,
        app__py=HELLO,
        other__py=GONE,
        test_app__py=TESTS,
        requirements__txt="acme-kit==1.0\n",
    )
    result = tried(root, "--yes", "--branch", "--agent", "claude_code")
    assert result.exit_code == 0, result.output
    assert "0 file(s) were edited, 1 place(s) need no edit, 0 place(s) are left" in result.output
    name = "obelize/upgrade-acme-kit-2.0"
    said = git(root, "log", "-1", "--format=%B", name).stdout.decode()
    assert (
        "A model said 1 flagged place(s) need no edit (other.py:5); only the tests checked" in said
    )
    assert git(root, "show", f"{name}:other.py").stdout.decode() == GONE
    assert git(root, "show", f"{name}:requirements.txt").stdout.decode() != "acme-kit==1.0\n"


def test_a_claim_that_a_place_needs_no_edit_is_wrong_when_a_test_breaks(
    trial: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = agent_world(trial, monkeypatch, Unchanged())
    result = tried(root, "--yes", "--branch", "--agent", "claude_code")
    assert result.exit_code == 3, result.output
    assert "broke: test_app::test_gone" in result.output
    assert git(root, "branch", "--list", "obelize/*").stdout.decode().strip() == ""


def test_a_dependency_line_with_extras_is_left_and_the_commit_says_so(trial: Path) -> None:
    root = repo(
        trial,
        pdf__py=PDF,
        test_pdf__py="import pdf\n\n\ndef test_imports():\n    assert pdf.pages\n",
        requirements__txt="PyPDF2[crypto]==3.0.1\n",
    )
    result = runner.invoke(
        app,
        [
            "upgrade",
            "PyPDF2",
            "--repo",
            str(root),
            "--python",
            PYTHON,
            "--apply",
            "--yes",
            "--branch",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "The dependency line at requirements.txt:1 could not be written" in result.output
    name = "obelize/upgrade-pypdf-6.19"
    said = git(root, "log", "-1", "--format=%B", name).stdout.decode()
    assert "Not written, for you to change: the dependency line at requirements.txt:1." in said
    shown = git(root, "show", "--stat", "--format=", name).stdout.decode()
    assert "pdf.py" in shown
    assert "requirements.txt" not in shown


def test_a_declaration_that_stops_the_rules_is_said_when_the_trial_cannot_judge(
    trial: Path,
) -> None:
    root = repo(trial, app__py=HELLO, test_app__py=TESTS, requirements__txt="acme-kit<2\n")
    result = tried(root, "--yes", "--from", "1.0")
    assert result.exit_code == 6, result.output
    assert "requirements.txt declares acme-kit <2" in result.output
    assert "allows versions this migration does not cover" in result.output
    assert "test(s) passed before" not in result.output
    assert (root / "app.py").read_text() == HELLO
