"""What `run.json` records about the tree, and when the dirty-tree gate refuses.

`HEAD` is recorded only at a repository's top, because `git -C <dir>` answers for the enclosing
repository; dirt is the whole repository's, and a git that does not answer is not clean.
`tree` reads `--porcelain -z` because v1 quotes the non-ASCII paths a refusal has to name.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from obelize import fsutil, gitutil
from obelize.native import processes
from platforms import program, windows_only

HEX = 40


def modified(root: Path) -> tuple[str, ...]:
    found = gitutil.tree(root)
    assert found is not None
    return found.modified


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "work")
    _git(root, "config", "user.name", "obelize tests")
    _git(root, "config", "user.email", "tests@obelize.invalid")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    return root


def test_a_clean_repository_reports_its_head_and_its_branch(repository: Path) -> None:
    state = gitutil.state(repository)
    assert len(state.sha or "") == HEX
    assert state.branch == "work"
    assert state.dirty is False


def test_a_modified_tracked_file_is_dirty(repository: Path) -> None:
    (repository / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert gitutil.state(repository).dirty is True


def test_an_untracked_file_is_not(repository: Path) -> None:
    """Obelize writes `.obelize/` itself, so counting it would make every later run dirty."""
    (repository / ".obelize" / "runs").mkdir(parents=True)
    (repository / ".obelize" / "latest").write_text("x\n", encoding="utf-8")
    assert gitutil.state(repository).dirty is False


def test_a_detached_head_has_a_commit_and_no_branch(repository: Path) -> None:
    _git(repository, "checkout", "-q", "--detach", "HEAD")
    state = gitutil.state(repository)
    assert len(state.sha or "") == HEX
    assert state.branch is None


def test_a_repository_with_no_commit_yet_has_neither(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    _git(root, "init", "-q", "-b", "work")
    state = gitutil.state(root)
    assert state.sha is None
    # `symbolic-ref` answers before the first commit: the branch exists, the commit does not.
    assert state.branch == "work"
    assert state.dirty is False


def test_a_directory_inside_a_repository_is_not_that_repository(repository: Path) -> None:
    inner = repository / "packages" / "thing"
    inner.mkdir(parents=True)
    assert gitutil.is_toplevel(inner) is False
    assert gitutil.state(inner) == gitutil.State()


def test_a_directory_in_no_repository_at_all_is_not_one(tmp_path: Path) -> None:
    assert gitutil.is_toplevel(tmp_path) is False
    assert gitutil.state(tmp_path) == gitutil.State(sha=None, branch=None, dirty=False)


DECLINES = [
    (OSError("no git here"), "git is not installed"),
    (subprocess.TimeoutExpired(cmd="git", timeout=gitutil.TIMEOUT_S), "git did not answer"),
]


@pytest.mark.parametrize(("error", "why"), DECLINES, ids=["not-installed", "timed-out"])
def test_every_way_git_can_decline_reads_as_no_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception, why: str
) -> None:
    """A hung filesystem must not hold a scan open, and a machine with no git must not fail one."""

    def refuse(*_args: object, **_kwargs: object) -> object:
        raise error

    monkeypatch.setattr(subprocess, "run", refuse)
    assert gitutil.run(tmp_path, "status") is None, why
    assert gitutil.state(tmp_path) == gitutil.State(), why


def test_git_is_given_a_deadline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Only a call given a timeout can raise `TimeoutExpired`."""
    seen: dict[str, object] = {}

    def capture(command: list[str], **keywords: object) -> object:
        seen.update(keywords)
        raise OSError("enough")

    monkeypatch.setattr(subprocess, "run", capture)
    gitutil.run(tmp_path, "status")
    assert seen["timeout"] == gitutil.TIMEOUT_S
    assert seen["check"] is False


def test_a_clean_repository_has_nothing_outstanding(repository: Path) -> None:
    """`()` and `None` are different answers: clean, against no repository."""
    assert gitutil.tree(repository) == gitutil.Tree(toplevel=True, modified=())
    assert gitutil.tree(repository.parent) is None


def test_a_change_in_the_working_tree_is_named(repository: Path) -> None:
    (repository / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert modified(repository) == ("app.py",)


def test_a_change_in_the_index_alone_is_named(repository: Path) -> None:
    """Staged work is uncommitted too, and `--apply` would overwrite it."""
    (repository / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repository, "add", "app.py")
    assert modified(repository) == ("app.py",)


def test_an_untracked_file_is_not_outstanding(repository: Path) -> None:
    (repository / ".obelize").mkdir()
    (repository / ".obelize" / "latest").write_text("x\n", encoding="utf-8")
    assert modified(repository) == ()


def test_a_staged_rename_names_both_ends_of_it(repository: Path) -> None:
    """Both names are uncommitted work; the origin arrives as a status-less record of its own."""
    (repository / "other.py").write_text("OTHER = 1\n", encoding="utf-8")
    _git(repository, "add", "other.py")
    _git(repository, "commit", "-q", "-m", "second")
    _git(repository, "mv", "app.py", "renamed.py")
    assert modified(repository) == ("app.py", "renamed.py")


def test_a_path_that_needs_quoting_is_named_as_it_is_spelled(repository: Path) -> None:
    awkward = "caf\u00e9 notes.py"
    (repository / awkward).write_text("NOTE = 1\n", encoding="utf-8")
    _git(repository, "add", awkward)
    assert modified(repository) == (awkward,)


def test_a_directory_inside_a_repository_records_the_whole_tree_s_state(
    repository: Path,
) -> None:
    inner = repository / "packages" / "thing"
    inner.mkdir(parents=True)
    assert gitutil.state(inner) == gitutil.State(dirty=False)
    (repository / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert gitutil.state(inner) == gitutil.State(dirty=True)


def test_a_directory_inside_a_repository_is_gated_on_the_whole_repository(
    repository: Path,
) -> None:
    inner = repository / "packages" / "thing"
    inner.mkdir(parents=True)
    (repository / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    stopped = fsutil.gate(inner, [])
    assert stopped is not None
    assert stopped.dirty == ("app.py",)


@pytest.mark.skipif(
    not Path(str(Path.cwd()).swapcase()).exists(), reason="a case-sensitive filesystem"
)
def test_the_root_spelled_in_another_case_is_the_root(repository: Path) -> None:
    """macOS opens `/TMP/Repo` as `/tmp/repo` and git answers; a string comparison would not."""
    other = Path(str(repository).swapcase())
    (repository / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    state = gitutil.state(other)
    assert state.dirty is True
    assert state.sha is not None
    stopped = fsutil.gate(other, [])
    assert stopped is not None
    assert stopped.dirty == ("app.py",)


def test_a_repository_whose_status_fails_is_not_a_clean_one(
    monkeypatch: pytest.MonkeyPatch, repository: Path
) -> None:
    """git found the repository but would not describe it: bad index, `safe.directory`, timeout."""
    real = gitutil.run

    def decline(root: Path, *arguments: str) -> str | None:
        return None if arguments[0] == "status" else real(root, *arguments)

    monkeypatch.setattr(gitutil, "run", decline)
    assert gitutil.state(repository).dirty is None
    stopped = fsutil.gate(repository, [])
    assert stopped is not None
    assert stopped.blocked


@pytest.mark.parametrize(("error", "why"), DECLINES, ids=["not-installed", "timed-out"])
def test_every_way_git_can_decline_inside_a_repository_is_not_an_answer(
    monkeypatch: pytest.MonkeyPatch, repository: Path, error: Exception, why: str
) -> None:
    """Outside a repository these mean "no repository"; beside a `.git` they are unanswered."""

    def refuse(*_args: object, **_kwargs: object) -> object:
        raise error

    monkeypatch.setattr(subprocess, "run", refuse)
    assert gitutil.state(repository).dirty is None, why
    stopped = fsutil.gate(repository, [])
    assert stopped is not None, why
    assert stopped.blocked, why


def test_a_relative_root_looks_for_git_above_where_it_is(
    monkeypatch: pytest.MonkeyPatch, repository: Path
) -> None:
    """`Path(".").parents` is empty, so the search must start from the absolute path."""
    inner = repository / "packages"
    inner.mkdir()
    monkeypatch.chdir(inner)

    def refuse(*_args: object, **_kwargs: object) -> object:
        raise OSError("no git here")

    monkeypatch.setattr(subprocess, "run", refuse)
    assert gitutil.state(Path(".")).dirty is None


def test_a_git_found_nowhere_answers_nothing_so_the_apply_is_refused(
    monkeypatch: pytest.MonkeyPatch, repository: Path
) -> None:
    """Windows looks git up on `PATH` alone, stubbed here as finding none; nothing else is run."""

    def nowhere() -> str:
        raise FileNotFoundError("no git.com or git.exe in the command's PATH")

    monkeypatch.setattr(processes, "git", nowhere)
    assert gitutil.run(repository, "rev-parse", "HEAD") is None
    assert gitutil.state(repository).dirty is None
    stopped = fsutil.gate(repository, [])
    assert stopped is not None
    assert stopped.blocked


@windows_only("POSIX looks git up on PATH alone; the stubbed test above shows the lookup is asked")
def test_a_git_planted_where_obelize_runs_is_never_run(
    monkeypatch: pytest.MonkeyPatch, repository: Path, tmp_path: Path
) -> None:
    """Control: `CreateProcess` looks in the current directory before `PATH`, so a bare `git`
    runs the planted one. A `PATH` not seen before makes obelize look git up afresh.
    """
    head = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], check=True, capture_output=True
    ).stdout.strip()
    program(repository / "git", passes=True)
    monkeypatch.chdir(repository)
    monkeypatch.setenv("PATH", f"{tmp_path / 'unlisted'}{os.pathsep}{os.environ['PATH']}")
    planted = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, check=False)
    assert planted.stdout.strip() != head
    assert gitutil.state(repository).sha == head.decode("ascii")


def test_the_git_that_runs_is_the_first_one_on_path(
    monkeypatch: pytest.MonkeyPatch, repository: Path, tmp_path: Path
) -> None:
    """Control: the git already on `PATH` answers, so the one put before it is what fails."""
    assert gitutil.run(repository, "rev-parse", "HEAD") is not None
    listed = tmp_path / "listed"
    listed.mkdir()
    program(listed / "git", passes=False)
    monkeypatch.setenv("PATH", f"{listed}{os.pathsep}{os.environ['PATH']}")
    assert gitutil.run(repository, "rev-parse", "HEAD") is None


def test_a_directory_inside_git_s_own_is_not_an_answer(repository: Path) -> None:
    """`.git/` is in the repository and in no work tree: git says `false`."""
    stopped = fsutil.gate(repository / ".git", [])
    assert stopped is not None
    assert stopped.blocked


def test_permission_to_write_on_a_dirty_tree_covers_one_nobody_could_read(
    monkeypatch: pytest.MonkeyPatch, repository: Path
) -> None:
    """`--allow-dirty` skips the question, so an unanswerable one cannot stop it."""
    monkeypatch.setattr(gitutil, "run", lambda *_args: None)
    assert fsutil.gate(repository, [], allow_dirty=True) is None


def test_git_in_the_suite_reads_no_configuration_of_this_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """GitHub's Windows runners set `core.autocrlf` system-wide; a user's own file can sign commits.

    Both are planted here, so the test does not depend on what this machine happens to hold.
    """
    planted = "[core]\n\tautocrlf = true\n"
    (tmp_path / "system").write_text(planted, encoding="utf-8")
    (tmp_path / ".gitconfig").write_text(planted, encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "system"))
    monkeypatch.setenv("HOME", str(tmp_path))
    listed = subprocess.run(
        ["git", "config", "--list"], cwd=tmp_path, check=True, capture_output=True
    )
    assert listed.stdout == b""


def untracked(root: Path, *planned: str) -> tuple[str, ...]:
    found = gitutil.tree(root, planned)
    assert found is not None
    return found.untracked


def change(root: Path, name: str) -> fsutil.Change:
    data = (root / name).read_bytes()
    return fsutil.Change(path=name, before=data, after=data + b"# migrated\n")


def test_a_planned_file_git_does_not_track_is_named(repository: Path) -> None:
    (repository / "new.py").write_text("NEW = 1\n", encoding="utf-8")
    (repository / "loose.py").write_text("LOOSE = 1\n", encoding="utf-8")
    assert untracked(repository, "app.py", "new.py") == ("new.py",)


def test_a_planned_file_below_the_top_is_spelled_from_the_top(repository: Path) -> None:
    inner = repository / "packages" / "thing"
    inner.mkdir(parents=True)
    (inner / "new.py").write_text("NEW = 1\n", encoding="utf-8")
    assert untracked(inner, "new.py") == ("packages/thing/new.py",)


def test_the_state_of_a_tree_does_not_list_its_index(
    monkeypatch: pytest.MonkeyPatch, repository: Path
) -> None:
    """Every scan records the state, and only a plan needs the listing."""
    asked: list[str] = []
    real = gitutil.run

    def spy(root: Path, *arguments: str) -> str | None:
        asked.append(arguments[0])
        return real(root, *arguments)

    monkeypatch.setattr(gitutil, "run", spy)
    assert gitutil.state(repository).dirty is False
    assert "status" in asked
    assert "ls-files" not in asked


def test_an_index_git_will_not_list_is_not_an_answer(
    monkeypatch: pytest.MonkeyPatch, repository: Path
) -> None:
    real = gitutil.run

    def decline(root: Path, *arguments: str) -> str | None:
        return None if arguments[0] == "ls-files" else real(root, *arguments)

    monkeypatch.setattr(gitutil, "run", decline)
    with pytest.raises(gitutil.UnansweredError):
        gitutil.tree(repository, ["app.py"])
    assert fsutil.gate(repository, [change(repository, "app.py")]) == fsutil.Apply(unknown=True)


def test_an_untracked_file_on_the_plan_refuses_the_apply_unless_allowed(
    repository: Path,
) -> None:
    """`git diff` cannot show its rewrite, nor `git checkout` undo it; one off the plan is fine."""
    (repository / "new.py").write_text("NEW = 1\n", encoding="utf-8")
    (repository / "loose.py").write_text("LOOSE = 1\n", encoding="utf-8")
    assert fsutil.gate(repository, [change(repository, "app.py")]) is None
    planned = [change(repository, "app.py"), change(repository, "new.py")]
    assert fsutil.gate(repository, planned) == fsutil.Apply(dirty=("new.py",), untracked=True)
    assert fsutil.gate(repository, planned, allow_dirty=True) is None


def test_every_outstanding_path_is_named_once_in_path_order(repository: Path) -> None:
    """`git rm --cached` leaves a file git reports as deleted and no longer tracks."""
    tracked = [f"t{index}.py" for index in range(6)]
    for name in tracked:
        (repository / name).write_text("T = 1\n", encoding="utf-8")
    _git(repository, "add", *tracked)
    _git(repository, "commit", "-q", "-m", "more")
    for name in tracked:
        (repository / name).write_text("T = 2\n", encoding="utf-8")
    loose = [f"a{index}.py" for index in range(6)]
    for name in loose:
        (repository / name).write_text("A = 1\n", encoding="utf-8")
    _git(repository, "rm", "-q", "--cached", "app.py")
    stopped = fsutil.gate(repository, [change(repository, name) for name in ["app.py", *loose]])
    assert stopped == fsutil.Apply(dirty=tuple(sorted(["app.py", *tracked, *loose])))
