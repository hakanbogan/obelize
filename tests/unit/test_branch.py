"""`obelize.branch`: a commit on a new branch that touches nothing else."""

from __future__ import annotations

import stat
import sys
from typing import TYPE_CHECKING

import pytest

from obelize import branch
from obelize.native import processes
from support import committed, git, write_tree

if TYPE_CHECKING:
    from pathlib import Path


def repo(tmp_path: Path) -> Path:
    root = committed(tmp_path / "repo", {"app.py": "old = 1\n", "docs/readme.txt": "hi\n"})
    return root


def shown(root: Path, *arguments: str) -> str:
    return git(root, *arguments).stdout.decode()


def test_the_changes_are_one_commit_on_a_new_branch_and_the_working_tree_is_left_alone(
    tmp_path: Path,
) -> None:
    root = repo(tmp_path)
    (root / "app.py").write_text("old = 1\n# edited by hand\n")
    (root / "scratch.txt").write_text("untracked")
    head = shown(root, "rev-parse", "HEAD").strip()
    made = branch.commit(
        root, "obelize/up", {"app.py": b"new = 2\n", "added.py": b"x = 1\n"}, "Move\n\nbody\n"
    )
    assert made == shown(root, "rev-parse", "obelize/up").strip()
    assert shown(root, "rev-parse", "obelize/up^").strip() == head
    assert shown(root, "show", "obelize/up:app.py") == "new = 2\n"
    assert shown(root, "show", "obelize/up:added.py") == "x = 1\n"
    assert shown(root, "show", "obelize/up:docs/readme.txt") == "hi\n"
    assert shown(root, "log", "-1", "--format=%B", "obelize/up").startswith("Move\n\nbody")
    assert (root / "app.py").read_text() == "old = 1\n# edited by hand\n"
    assert (root / "scratch.txt").exists()
    assert shown(root, "branch", "--show-current").strip() == "work"
    assert shown(root, "status", "--porcelain").splitlines() == [" M app.py", "?? scratch.txt"]
    assert shown(root, "diff", "--cached").strip() == ""


def test_no_hook_runs_and_nothing_is_signed(tmp_path: Path) -> None:
    root = repo(tmp_path)
    hooks = root / ".git" / "hooks"
    for hook in ("pre-commit", "commit-msg", "post-commit", "reference-transaction"):
        (hooks / hook).write_text(f"#!/bin/sh\ntouch '{tmp_path}/ran-{hook}'\nexit 1\n")
        (hooks / hook).chmod(0o755)
    git(root, "config", "commit.gpgsign", "true")
    git(root, "config", "gpg.program", "/nonexistent")
    branch.commit(root, "obelize/up", {"app.py": b"new = 2\n"}, "Move\n")
    assert not list(tmp_path.glob("ran-*"))
    assert "gpgsig" not in shown(root, "cat-file", "-p", "obelize/up")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no executable bit")
def test_an_executable_file_stays_executable_and_a_new_one_is_plain(tmp_path: Path) -> None:
    root = committed(tmp_path / "repo", {"run.sh": "#!/bin/sh\n", "other.py": "x\n"})
    (root / "run.sh").chmod(0o755)
    git(root, "add", "run.sh")
    git(root, "commit", "-qm", "executable")
    branch.commit(
        root, "obelize/up", {"run.sh": b"#!/bin/sh\necho\n", "fresh.py": b"y\n"}, "Move\n"
    )
    modes = {
        line.split()[-1]: line.split()[0]
        for line in shown(root, "ls-tree", "obelize/up").splitlines()
    }
    assert modes["run.sh"] == "100755"
    assert modes["fresh.py"] == "100644"
    assert not stat.S_ISDIR(0)


def test_a_repository_below_the_top_commits_paths_below_it(tmp_path: Path) -> None:
    root = tmp_path / "mono"
    committed(root, {"service/app.py": "old\n", "other/app.py": "keep\n"})
    branch.commit(root / "service", "obelize/up", {"app.py": b"new\n"}, "Move\n")
    assert shown(root, "show", "obelize/up:service/app.py") == "new\n"
    assert shown(root, "show", "obelize/up:other/app.py") == "keep\n"


@pytest.mark.parametrize("name", ["bad name", "a..b", "-x", "x.lock", ""])
def test_a_name_git_would_not_accept_is_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(branch.BranchError, match="not a name git accepts"):
        branch.commit(repo(tmp_path), name, {"app.py": b"x"}, "m\n")


def test_a_branch_that_exists_is_never_moved(tmp_path: Path) -> None:
    root = repo(tmp_path)
    git(root, "branch", "taken")
    before = shown(root, "rev-parse", "taken")
    with pytest.raises(branch.BranchError, match="exists already"):
        branch.commit(root, "taken", {"app.py": b"x"}, "m\n")
    assert shown(root, "rev-parse", "taken") == before


def test_a_repository_with_no_commit_has_nothing_to_build_on(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    write_tree(root, {"a.py": "x\n"})
    git(root.parent, "init", "-q", str(root))
    with pytest.raises(branch.BranchError, match="no commit"):
        branch.commit(root, "obelize/up", {"a.py": b"y"}, "m\n")


def test_a_committer_git_does_not_know_is_an_error_with_what_git_said(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo(tmp_path)
    git(root, "config", "--unset", "user.name")
    git(root, "config", "--unset", "user.email")
    for name in (
        "GIT_AUTHOR_NAME",
        "GIT_COMMITTER_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_EMAIL",
        "EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "empty.gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.useConfigOnly")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(branch.BranchError, match="git commit-tree failed"):
        branch.commit(root, "obelize/up", {"app.py": b"x"}, "m\n")


def test_git_that_will_not_run_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(processes, "git", lambda: str(tmp_path / "no-such-git"))
    with pytest.raises(branch.BranchError, match="did not run"):
        branch.commit(repo(tmp_path), "obelize/up", {"app.py": b"x"}, "m\n")
