"""A selected file the scan could not read, and a file the search for a version could not read.

A pack with one distribution for both APIs cannot tell from an import which API a file uses, so a
`.py` file it could not read holds the pin as a notebook it does not analyse does, and a raised
`max_file_bytes` clears it. A file over the search limit is named where the run took a release.
"""

from __future__ import annotations

import errno
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pdf_repo import MAIN, SPEC, git_repo
from typer.testing import CliRunner

from obelize import fsutil
from obelize.cli import app
from obelize.models import Config
from obelize.packs import loader
from obelize.scan import installed, runner
from platforms import PYTHON
from support import committed, write_tree

OPENAI = loader.to_scan_spec(loader.load("openai/openai-0-to-1"))
CALL = "import openai\n\nresponse = openai.ChatCompletion.create(model='m', messages=[])\n"
FILES = {"app.py": CALL, "big.py": "value = 1\n" * 100, "requirements.txt": "openai==0.28.1\n"}


def scan(root: Path, limit: int = 2_000_000, spec: Any = OPENAI) -> runner.Scan:
    return runner.scan(root, Config(max_file_bytes=limit), spec, jobs=1)


def pins(found: runner.Scan) -> list[tuple[str, str, str | None]]:
    return [(row.path, row.scan_status, row.bail) for row in found.manifests.findings]


def test_a_file_over_the_size_limit_holds_the_pin_of_a_pack_with_one_distribution(
    tmp_path: Path,
) -> None:
    found = scan(write_tree(tmp_path, FILES), limit=200)
    assert found.unanalysed == ("big.py",)
    assert found.manifests.blocking == ("big.py",)
    assert pins(found) == [("requirements.txt", "needs_review", "repo_not_fully_migrated")]
    (row,) = found.limitations
    assert (row.path, row.code) == ("big.py", "file_too_large")
    assert row.detail.endswith(runner.HOLDS)
    assert "200" in row.detail


def test_a_raised_limit_clears_the_hold(tmp_path: Path) -> None:
    found = scan(write_tree(tmp_path, FILES))
    assert (found.unanalysed, found.limitations) == ((), ())
    assert pins(found) == [("requirements.txt", "eligible", None)]


def test_a_file_the_user_excludes_holds_nothing(tmp_path: Path) -> None:
    config = Config(max_file_bytes=200, exclude=("big.py",))
    found = runner.scan(write_tree(tmp_path, FILES), config, OPENAI, jobs=1)
    assert found.unanalysed == ()
    assert pins(found) == [("requirements.txt", "eligible", None)]
    assert [(row.path, runner.HOLDS in row.detail) for row in found.limitations] == [
        ("big.py", False)
    ]


def test_a_file_that_cannot_be_opened_holds_it_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read = fsutil.read

    def refuse(path: Path, *arguments: Any) -> bytes:
        if path.name == "big.py":
            raise PermissionError(errno.EACCES, "denied")
        return read(path, *arguments)

    monkeypatch.setattr(fsutil, "read", refuse)
    found = scan(write_tree(tmp_path, FILES))
    assert found.unanalysed == ("big.py",)
    assert pins(found) == [("requirements.txt", "needs_review", "repo_not_fully_migrated")]
    (row,) = found.limitations
    assert (row.path, row.code) == ("big.py", "unreadable")
    assert row.detail.endswith(runner.HOLDS)


def test_a_pack_with_two_distributions_holds_nothing_for_it(tmp_path: Path) -> None:
    files = {"main.py": MAIN, "big.py": "value = 1\n" * 100, "requirements.txt": "PyPDF2==3.0.1\n"}
    found = scan(write_tree(tmp_path, files), limit=200, spec=SPEC)
    assert found.unanalysed == ()
    assert pins(found) == [("requirements.txt", "eligible", None)]
    (row,) = found.limitations
    assert (row.path, row.code) == ("big.py", "file_too_large")
    assert runner.HOLDS not in row.detail


runner_ = CliRunner()


def test_a_run_writes_nothing_while_a_file_cannot_be_read_and_says_which(tmp_path: Path) -> None:
    tree = committed(tmp_path / "repo", {**FILES, ".obelize.yml": "max_file_bytes: 200\n"})
    result = runner_.invoke(
        app,
        ["fix", "--apply", "--allow-dirty", "--verify", f"{PYTHON} -c pass", "--repo", str(tree)],
    )
    assert result.exit_code == 4, result.output
    assert "Not migrated by obelize, so they hold the pin: big.py." in result.output
    for path, text in FILES.items():
        assert (tree / path).read_text(encoding="utf-8") == text, path


# The search for a version.

NOTES = "x" * 300


def searched(
    root: Path, monkeypatch: pytest.MonkeyPatch, limit: int = 200
) -> tuple[runner.Scan, tuple[tuple[str, str], ...]]:
    monkeypatch.setattr(installed, "_LIMIT", limit)
    found = scan(root, limit=100, spec=SPEC)
    return found, found.assumed


def test_a_file_over_the_search_limit_is_named_where_the_run_took_a_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = git_repo(tmp_path, {"requirements.txt": "PyPDF2\n", "main.py": MAIN, "notes.txt": NOTES})
    found, assumed = searched(root, monkeypatch)
    assert assumed == (("PyPDF2", "3.0.1"),)
    (row,) = found.limitations
    assert (row.path, row.code) == ("notes.txt", "file_too_large")
    assert "300 bytes, over the 200" in row.detail
    assert "PyPDF2" in row.detail


@pytest.mark.parametrize(
    ("files", "named"),
    [
        ({"requirements.txt": "PyPDF2\n", "notes.txt": "x" * 150}, False),
        ({"requirements.txt": "PyPDF2==3.0.1\n", "notes.txt": NOTES}, False),
        ({"requirements.txt": "PyPDF2\n", "notes.txt": "PyPDF2==1.26.0\n" + "x" * 150}, False),
    ],
    ids=["under-the-limit", "no-release-taken", "release-ruled-out"],
)
def test_a_file_is_not_named_where_it_cannot_have_mattered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: Mapping[str, str], named: bool
) -> None:
    root = git_repo(tmp_path, {"main.py": MAIN, **files})
    found, _ = searched(root, monkeypatch)
    assert any(row.path == "notes.txt" for row in found.limitations) is named


def test_a_listed_name_that_is_gone_is_not_a_file_over_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = git_repo(tmp_path, {"requirements.txt": "PyPDF2\n", "main.py": MAIN, "notes.txt": NOTES})
    monkeypatch.setattr(installed, "_LIMIT", 200)
    walk = runner.read(root, Config(), (SPEC,)).walk
    listed = replace(walk, listed=(*walk.listed, "ghost.txt"))
    assert [row.path for row in installed.unsearched(root, listed, SPEC)] == ["notes.txt"]
    (root / "notes.txt").unlink()
    assert installed.unsearched(root, listed, SPEC) == ()
