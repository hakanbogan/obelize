"""`obelize upgrade`: one dependency to a newer release, with the pack that exists or one made."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

import fakeindex
from obelize.cli import app
from obelize.packtools import synth
from support import committed

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()

V1 = "def old_greet(name):\n    return name\n\ndef removed_fn(x):\n    return x\n"
V15 = (
    "import warnings\n\ndef greet(name):\n    return name\n\n"
    "def old_greet(name):\n"
    "    warnings.warn('old_greet is deprecated, use greet instead', DeprecationWarning)\n"
    "    return greet(name)\n\ndef removed_fn(x):\n    return x\n"
)
V2 = "def greet(name):\n    return name\n"
APP = "import acme_kit\n\n\ndef run(name):\n    return acme_kit.old_greet(name)\n"
PDF = "import PyPDF2\n\n\ndef pages(path):\n    return PyPDF2.PdfReader(path).pages\n"


@pytest.fixture(scope="module")
def served() -> Iterator[fakeindex.FakeIndex]:
    for found in fakeindex.FakeIndex().serve():
        for version, source in (("1.0", V1), ("1.5", V15), ("2.0", V2)):
            found.add("acme-kit", version, {"__init__.py": source}, module="acme_kit")
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
