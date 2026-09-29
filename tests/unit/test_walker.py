"""File selection: the git and fallback listings of one built tree, each under two roots.

One is under `/tmp`, a macOS symlink: resolving only the candidate there finds no escape, just
an empty repository. `tests/fixtures/walker/_build.py` builds the tree and its answer key, as a
checkout cannot hold a nested `.git`, a symlink loop or an unreadable directory.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from obelize.config import ConfigError, load
from obelize.models import SKIP_REASONS, Config
from obelize.native import files
from obelize.scan import walker
from obelize.scan.walker import Walk, git_listing, walk
from platforms import AS_ROOT, deny, junction, posix_only, windows_only

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "walker"


def _load_builder() -> Any:
    """Import `_build.py` by path: it is a fixture generator, not a package."""
    spec = importlib.util.spec_from_file_location("obelize_walker_fixture", FIXTURES / "_build.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    # Bytecode left in a fixture directory would travel with every copy of it.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


fixture = _load_builder()

TMP = posix_only("only POSIX has /tmp, which macOS makes a link")


@pytest.fixture(
    scope="session",
    params=["private", pytest.param("tmp", marks=TMP)],
    ids=["tmp_path", "under_tmp"],
)
def workspace(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Path]:
    """One root pytest chose and one under `/tmp`."""
    if request.param == "tmp":
        base = Path(tempfile.mkdtemp(dir="/tmp", prefix="obelize-walker-"))
    else:
        base = tmp_path_factory.mktemp("walker")
    yield base
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture(scope="session")
def git_tree(workspace: Path) -> Iterator[Path]:
    """The fixture tree as a git repository; `git add` must read `sealed/` before it is denied."""
    root = workspace / "checkout"
    fixture.build(root)
    fixture.initialise(root)
    with deny(root / "sealed"):
        yield root


@pytest.fixture(scope="session")
def plain_tree(workspace: Path) -> Iterator[Path]:
    """The same tree with no repository, so the fallback answers."""
    root = workspace / "plain"
    fixture.build(root)
    with deny(root / "sealed"):
        yield root


def _configured(root: Path) -> Config:
    return load(root).config


def _table(result: Walk) -> dict[str, str]:
    return {row.path: row.reason for row in result.skipped}


def test_the_git_listing_answers_for_a_repository(git_tree: Path) -> None:
    result = walk(git_tree, _configured(git_tree))
    assert result.source == "git"
    assert result.files == fixture.SELECTED


def test_the_walk_answers_when_git_does_not(plain_tree: Path) -> None:
    result = walk(plain_tree, _configured(plain_tree))
    assert result.source == "walk"
    assert result.files == tuple(sorted(fixture.SELECTED + fixture.IGNORED_BY_GIT))


def test_the_two_listings_differ_only_over_what_gitignore_says(
    git_tree: Path, plain_tree: Path
) -> None:
    """git is right: the fallback lists ignored `build_out/x.py` and `generated/pb2.py`, both
    legacy imports and neither anybody's source (ADR-008)."""
    by_git = walk(git_tree, _configured(git_tree))
    by_walk = walk(plain_tree, _configured(plain_tree))
    assert set(by_walk.files) - set(by_git.files) == set(fixture.IGNORED_BY_GIT)
    assert set(by_git.files) - set(by_walk.files) == set()
    assert by_git.excluded == by_walk.excluded == fixture.EXCLUDED


def test_a_git_listing_is_used_only_when_it_describes_this_root(git_tree: Path) -> None:
    """`git -C <dir> ls-files` answers for the enclosing checkout, whose index must not apply."""
    assert git_listing(git_tree) is not None
    assert git_listing(git_tree / "pkg") is None


def test_the_walk_runs_when_git_is_not_installed(
    git_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*arguments: Any, **keywords: Any) -> Any:
        raise OSError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(subprocess, "run", missing)
    assert walk(git_tree, Config()).source == "walk"


def test_the_walk_runs_when_git_answers_one_question_and_not_the_next(
    git_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ls-files` can fail after `rev-parse` succeeds, e.g. on a corrupt index."""
    real = subprocess.run

    def refuse_the_listing(argv: Any, **keywords: Any) -> Any:
        if "ls-files" in argv:
            return subprocess.CompletedProcess(argv, 1, b"", b"fatal: index file corrupt")
        return real(argv, **keywords)

    monkeypatch.setattr(subprocess, "run", refuse_the_listing)
    assert walk(git_tree, Config()).source == "walk"


@pytest.mark.skipif(AS_ROOT, reason="root reads the directory this table calls unreadable")
def test_the_git_listing_refuses_exactly_the_documented_paths(git_tree: Path) -> None:
    assert _table(walk(git_tree, _configured(git_tree))) == fixture.SKIPPED_BY_GIT


@pytest.mark.skipif(AS_ROOT, reason="root reads the directory this table calls unreadable")
def test_the_walk_refuses_exactly_the_documented_paths(plain_tree: Path) -> None:
    """Three rows more than git: work git does for free."""
    assert _table(walk(plain_tree, _configured(plain_tree))) == fixture.SKIPPED_BY_WALK


def test_the_walk_prunes_another_repository_rather_than_descending_into_it(
    plain_tree: Path,
) -> None:
    """The nested `.git` is the only signal; listing `vendorsub/sub_mod.py` would let an apply
    rewrite another repository, out of this diff's sight (ADR-008)."""
    result = walk(plain_tree, _configured(plain_tree))
    assert _table(result)["vendorsub"] == "submodule"
    assert not [name for name in result.files if name.startswith("vendorsub/")]


def test_a_submodule_reaches_a_git_listing_as_one_path_and_is_dropped_by_is_file(
    git_tree: Path,
) -> None:
    """`include` is widened to reach the guard; `ls-files` lists a submodule as one directory."""
    result = walk(git_tree, Config(include=fixture.EVERYTHING))
    assert _table(result)["vendorsub"] == "not_a_file"
    assert not [name for name in result.files if name.startswith("vendorsub/")]


@pytest.mark.skipif(AS_ROOT, reason="root reads the directory this table calls unreadable")
def test_widening_the_glob_hands_the_guard_everything_the_default_never_named(
    git_tree: Path,
) -> None:
    result = walk(git_tree, Config(include=fixture.EVERYTHING))
    assert _table(result) == fixture.SKIPPED_BY_GIT_INCLUDING_EVERYTHING


@pytest.mark.skipif(AS_ROOT, reason="root reads the directory this test makes unreadable")
def test_a_directory_that_will_not_be_listed_is_reported_rather_than_ignored(
    plain_tree: Path,
) -> None:
    """Dropped silently, its files would read as a clean repository."""
    assert _table(walk(plain_tree, _configured(plain_tree)))["sealed"] == "unreadable"


def test_a_virtual_environment_is_pruned_whatever_it_is_called(plain_tree: Path) -> None:
    """`pyvenv.cfg` (PEP 405) is the only marker every venv has."""
    result = walk(plain_tree, _configured(plain_tree))
    assert "venv_like/site.py" not in result.files
    assert "venv_like/site.py" not in _table(result)


def test_a_name_that_is_not_utf8_is_refused_by_the_name_a_report_can_print(
    git_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """macOS will not create this name, so the listing is faked at the subprocess boundary,
    keeping the real `surrogateescape` decode."""
    real = subprocess.run

    def listing(argv: Any, **keywords: Any) -> Any:
        if "ls-files" in argv:
            return subprocess.CompletedProcess(argv, 0, b"pkg/app.py\0bad\xff.py\0", b"")
        return real(argv, **keywords)

    monkeypatch.setattr(subprocess, "run", listing)
    result = walk(git_tree, Config())
    assert result.files == ("pkg/app.py",)
    assert _table(result) == {"bad\\xff.py": "unusable_name"}


def test_a_name_that_is_not_utf8_prints_the_same_where_fsencode_passes_surrogates(
    git_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' `os.fsencode` uses `surrogatepass`, which would print `bad\\xed\\xb3\\xbf.py`."""
    real = subprocess.run

    def listing(argv: Any, **keywords: Any) -> Any:
        if "ls-files" in argv:
            return subprocess.CompletedProcess(argv, 0, b"bad\xff.py\0", b"")
        return real(argv, **keywords)

    monkeypatch.setattr(subprocess, "run", listing)
    monkeypatch.setattr(os, "fsencode", lambda name: name.encode("utf-8", "surrogatepass"))
    assert _table(walk(git_tree, Config())) == {"bad\\xff.py": "unusable_name"}


def test_a_name_holding_a_lone_surrogate_is_refused_by_a_name_a_report_can_print(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Windows directory can list a UTF-16 surrogate no byte decoded to, which
    `surrogateescape` cannot encode; POSIX lists no such name, so the walk is faked."""
    (tmp_path / "app.py").write_bytes(b"x = 1\n")
    monkeypatch.setattr(
        os, "walk", lambda top, **_: iter([(str(top), [], ["app.py", "bad\ud800.py"])])
    )
    result = walk(tmp_path, Config())
    assert result.files == ("app.py",)
    assert _table(result) == {"bad\\ud800.py": "unusable_name"}


def test_a_listed_name_the_system_reserves_is_refused_by_name(
    git_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' answer, stubbed: an index can list `aux.py` there, which opens a device."""
    monkeypatch.setattr(files, "reserved", lambda name: name == "pkg/app.py")
    result = walk(git_tree, _configured(git_tree))
    assert "pkg/app.py" not in result.files
    assert _table(result)["pkg/app.py"] == "unusable_name"


@posix_only("a Windows name cannot hold a backslash")
def test_a_backslash_in_a_name_is_refused_for_the_same_reason(git_tree: Path) -> None:
    """Legal on POSIX, a separator elsewhere, and unreadable in a report."""
    assert _table(walk(git_tree, _configured(git_tree)))["weird\\name.py"] == "unusable_name"


def _backslashed_directory(root: Path) -> None:
    """A link too: refused as a link first, its row would carry the name as a path."""
    (root / "weird\\dir").mkdir()
    (root / "weird\\dir" / "app.py").write_bytes(b"import google.generativeai\n")
    (root / "weird\\link").symlink_to("weird\\dir", target_is_directory=True)
    (root / "app.py").write_bytes(b"x = 1\n")


@posix_only("a Windows name cannot hold a backslash")
def test_the_walk_refuses_a_directory_whose_name_holds_a_backslash_whole(tmp_path: Path) -> None:
    """No pattern can prune by that name and no report can name what it holds, so it is one
    row, like such a file, and nothing below it is looked at."""
    _backslashed_directory(tmp_path)
    result = walk(tmp_path, Config(include=fixture.EVERYTHING))
    assert result.source == "walk"
    assert result.files == ("app.py",)
    assert _table(result) == {"weird\\dir": "unusable_name", "weird\\link": "unusable_name"}


def test_the_walk_refuses_a_directory_whose_name_is_not_utf8_by_a_name_a_report_can_print(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """macOS will not create this name, so the walk is faked, with the `surrogateescape` name
    POSIX decodes it to."""
    (tmp_path / "app.py").write_bytes(b"x = 1\n")
    monkeypatch.setattr(os, "walk", lambda top, **_: iter([(str(top), ["bad\udcff"], ["app.py"])]))
    result = walk(tmp_path, Config())
    assert result.files == ("app.py",)
    assert _table(result) == {"bad\\xff": "unusable_name"}


def test_the_walk_refuses_a_nested_directory_the_system_reserves_by_its_whole_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' answer, stubbed, for a directory below another."""
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "app.py").write_bytes(b"x = 1\n")
    (tmp_path / "src" / "app.py").write_bytes(b"x = 1\n")
    monkeypatch.setattr(files, "reserved", lambda path: "pkg" in path.split("/"))
    result = walk(tmp_path, Config())
    assert result.source == "walk"
    assert result.files == ("src/app.py",)
    assert _table(result) == {"src/pkg": "unusable_name"}


@posix_only("a Windows name cannot hold a backslash")
def test_a_git_listing_refuses_each_file_below_such_a_directory(tmp_path: Path) -> None:
    """git lists files, not directories, so each is refused by the file rule."""
    _backslashed_directory(tmp_path)
    for arguments in (("init", "-q"), ("add", "-A")):
        subprocess.run(["git", "-C", str(tmp_path), *arguments], check=True, capture_output=True)
    result = walk(tmp_path, Config(include=fixture.EVERYTHING))
    assert result.source == "git"
    assert result.files == ("app.py",)
    assert _table(result) == {"weird\\dir/app.py": "unusable_name", "weird\\link": "unusable_name"}


def test_a_path_the_index_still_names_is_missing_rather_than_an_escape(
    git_tree: Path,
) -> None:
    """`rm` on a tracked file: an ordinary accident, not an attack."""
    assert _table(walk(git_tree, _configured(git_tree)))["deleted.py"] == "missing"


@pytest.mark.parametrize("path", fixture.INVISIBLE)
def test_the_selection_never_mentions_a_path_the_configuration_removed(
    git_tree: Path, plain_tree: Path, path: str
) -> None:
    """Without `.obelize/` always excluded, a second scan would find the first one's report."""
    for root in (git_tree, plain_tree):
        result = walk(root, _configured(root))
        assert path not in result.files
        assert path not in result.excluded
        assert path not in _table(result)


def test_an_excluded_file_is_named_rather_than_pruned(git_tree: Path, plain_tree: Path) -> None:
    """An excluded file still breaks the pin it imports, so `exclude` prunes no directory: the
    report must name each such file (ADR-010 F-2)."""
    for root in (git_tree, plain_tree):
        result = walk(root, _configured(root))
        assert result.excluded == fixture.EXCLUDED
        assert not set(result.excluded) & set(result.files)


def test_the_result_is_ordered_by_the_bytes_of_the_path(git_tree: Path, plain_tree: Path) -> None:
    """The documented sort key is the path's bytes; the runner appends the content hash."""
    for root in (git_tree, plain_tree):
        result = walk(root, _configured(root))
        assert list(result.files) == sorted(result.files, key=os.fsencode)
        assert list(result.excluded) == sorted(result.excluded, key=os.fsencode)
        assert [row.path for row in result.skipped] == sorted(
            (row.path for row in result.skipped), key=os.fsencode
        )


def test_two_walks_of_one_tree_are_the_same_walk(git_tree: Path) -> None:
    assert walk(git_tree, _configured(git_tree)) == walk(git_tree, _configured(git_tree))


def test_every_refusal_carries_a_published_reason_and_a_sentence(
    git_tree: Path, plain_tree: Path
) -> None:
    for root in (git_tree, plain_tree):
        for row in walk(root, _configured(root)).skipped:
            assert row.reason in SKIP_REASONS
            assert row.detail.endswith(".")


def test_a_sentence_exists_for_every_reason_the_vocabulary_declares() -> None:
    """`SCAN_VOCABULARY.md` section 11 is closed: a new reason without a sentence fails here."""
    assert set(walker._DETAIL) == SKIP_REASONS


def test_the_walker_opens_nothing(git_tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The reader owns the prefilter, `max_file_bytes` and parse gates, so a file is read once."""

    configured = _configured(git_tree)  # reading `.obelize.yml` is a read, and is not this

    def refuse(*arguments: Any, **keywords: Any) -> Any:
        raise AssertionError("the walker opened a file")

    monkeypatch.setattr(Path, "read_bytes", refuse)
    monkeypatch.setattr(Path, "read_text", refuse)
    monkeypatch.setattr(Path, "open", refuse)
    assert walk(git_tree, configured).files == fixture.SELECTED


def test_a_root_that_is_not_a_directory_is_a_usage_error(tmp_path: Path) -> None:
    """`os.walk` on a missing root silently yields nothing."""
    missing = tmp_path / "not-here"
    with pytest.raises(ConfigError, match="nothing to scan"):
        walk(missing, Config())
    a_file = tmp_path / "file.py"
    a_file.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="nothing to scan"):
        walk(a_file, Config())


def _manifests(root: Path) -> None:
    """Separate tree: adding to the walker fixture would move its three path tables."""
    for directory in ("src", "requirements", "scripts", "vendor"):
        (root / directory).mkdir()
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (root / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (root / "requirements" / "dev.txt").write_text("pytest\n", encoding="utf-8")
    (root / "setup.py").write_text("setup()\n", encoding="utf-8")
    (root / "notes.txt").write_text("not a manifest\n", encoding="utf-8")
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (root / "scripts" / "requirements.txt").write_text("old\n", encoding="utf-8")
    (root / "scripts" / "old.py").write_text("y = 2\n", encoding="utf-8")
    (root / "vendor" / "requirements.txt").write_text("theirs\n", encoding="utf-8")


def test_a_manifest_is_listed_although_include_never_matched_it(tmp_path: Path) -> None:
    """`include` defaults to `**/*.py`, so manifests match by name; `setup.py` is also source, and
    `vendor/` is always excluded."""
    _manifests(tmp_path)
    result = walk(tmp_path, Config())
    assert result.manifests == (
        "pyproject.toml",
        "requirements.txt",
        "requirements/dev.txt",
        "scripts/requirements.txt",
        "setup.py",
    )
    assert "setup.py" in result.files
    assert result.files == ("scripts/old.py", "setup.py", "src/app.py")


def test_a_manifest_the_user_excluded_is_not_read(tmp_path: Path) -> None:
    """An excluded `.py` is still named (ADR-010 F-2 reports its import); an excluded manifest is
    never written, so it is not read."""
    _manifests(tmp_path)
    result = walk(tmp_path, Config(exclude=("scripts/**",)))
    assert "scripts/requirements.txt" not in result.manifests
    assert result.excluded == ("scripts/old.py",)


def test_a_manifest_goes_through_the_path_guard_like_any_other_file(tmp_path: Path) -> None:
    """A symlink is never followed, whatever its name."""
    _manifests(tmp_path)
    (tmp_path / "requirements-linked.txt").symlink_to(tmp_path / "requirements.txt")
    result = walk(tmp_path, Config())
    assert "requirements-linked.txt" not in result.manifests
    assert ("requirements-linked.txt", "symlink") in {
        (row.path, row.reason) for row in result.skipped
    }


def test_a_file_include_leaves_out_that_can_hold_python_is_named(tmp_path: Path) -> None:
    """A notebook, a stub and a windowed script can import the legacy SDK; a text file cannot."""
    for name in ("app.py", "analysis.ipynb", "stubs.pyi", "gui.pyw", "notes.txt"):
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    result = walk(tmp_path, Config())
    assert result.files == ("app.py",)
    assert result.unincluded == ("analysis.ipynb", "gui.pyw", "stubs.pyi")


def test_the_fallback_walk_reports_a_junction_and_lists_nothing_below_it(
    plain_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' answer, stubbed: `os.walk` descends a junction, since `islink` is false for one."""
    monkeypatch.setattr(os.path, "isjunction", lambda path: os.path.basename(path) == "pkg")
    result = walk(plain_tree, _configured(plain_tree))
    assert _table(result)["pkg"] == "symlink"
    assert [name for name in result.files if name.startswith("pkg/")] == []


@windows_only("POSIX has no junction; the stubbed answer above stands in for one")
def test_a_real_junction_is_reported_and_not_descended(tmp_path: Path) -> None:
    """Control: `os.path.islink`, all the walk asked before, is false for it."""
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "app.py").write_bytes(b"x = 1\n")
    junction(tmp_path / "joined", tmp_path / "real")
    assert not os.path.islink(tmp_path / "joined")
    result = walk(tmp_path, Config())
    assert _table(result)["joined"] == "symlink"
    assert result.files == ("real/app.py",)
