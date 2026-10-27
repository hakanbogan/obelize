"""The upgrade mode of the action (`action/upgrade.py`): the job that runs the tests, the verdict on
its exit code, and the job that may write to the repository and checks what it is handed.

Everything the second job reads is forged in these tests with git's plumbing, because everything it
reads came from a job that ran code the second job does not trust.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from support import committed, load_script

ROOT = Path(__file__).resolve().parents[2]
NOT_ON_WINDOWS = pytest.mark.skipif(
    sys.platform == "win32", reason="a file system there holds no such name, and git changes it"
)
NEEDS_SH = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sh") is None,
    reason="the stand-in for uvx is a shell script, and GitHub runs these steps on ubuntu",
)


upgrade: Any = load_script(ROOT / "action" / "upgrade.py", "obelize_action_upgrade")
IDENTITY = upgrade.IDENTITY
OLD, NEW = "1.10.26", "pydantic>=2.12.5,<3"
SUBJECT = f"Upgrade pydantic {OLD} to {NEW}"
BRANCH = "obelize/upgrade-pydantic-2.12.5"
FILES = {
    "app.py": "x = 1\n",
    "tool.py": "#!/usr/bin/env python\ny = 1\n",
    "requirements.txt": "pydantic==1.10.26\n",
    "README.md": "hi\n",
}
Changes = dict[str, tuple[str, bytes] | None]
EDIT: Changes = {"app.py": ("100644", b"x = 2\n"), "requirements.txt": ("100644", b"pydantic>=2\n")}


def message(subject: str = SUBJECT, *, held: str = "") -> str:
    return (
        f"{subject}\n\nobelize 0.9.0 moved the code with the pack acme/x.\n"
        + (f"Not written, for you to change: the dependency line at {held}.\n" if held else "")
        + "\nObelize-Trial: 20261027T071500Z-ab12cd34\n"
    )


def plumb(
    root: Path, *args: str, env: dict[str, str] | None = None, data: bytes | None = None
) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args],
        input=data,
        capture_output=True,
        check=True,
        env={**os.environ, **(env or {})},
    )
    return done.stdout.decode().strip()


def craft(
    root: Path,
    branch: str,
    changes: Changes,
    *,
    text: str | None = None,
    parent: str | None = None,
    who: tuple[str, str] = IDENTITY,
) -> str:
    """A commit on `parent` (default `HEAD`) that sets each path to `(mode, bytes)` or removes it,
    pointed at by `refs/heads/<branch>`. A gitlink's bytes are the commit it names."""
    parent = parent or plumb(root, "rev-parse", "HEAD")
    with tempfile.TemporaryDirectory() as folder:
        env = {
            "GIT_INDEX_FILE": str(Path(folder) / "index"),
            "GIT_AUTHOR_NAME": who[0],
            "GIT_AUTHOR_EMAIL": who[1],
            "GIT_COMMITTER_NAME": who[0],
            "GIT_COMMITTER_EMAIL": who[1],
        }
        plumb(root, "read-tree", parent, env=env)
        for path, entry in changes.items():
            if entry is None:
                plumb(root, "update-index", "--force-remove", path, env=env)
                continue
            mode, data = entry
            if mode == "160000":
                blob = data.decode()
            else:
                blob = plumb(root, "hash-object", "-w", "--stdin", data=data)
            plumb(root, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}", env=env)
        tree = plumb(root, "write-tree", env=env)
        made = plumb(root, "commit-tree", tree, "-p", parent, "-m", text or message(), env=env)
    plumb(root, "update-ref", f"refs/heads/{branch}", made)
    return made


def trial(**changed: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "distribution": "pydantic",
        "from": OLD,
        "to": NEW,
        "status": "pass",
        "reason": None,
        "compared": 12,
        "broken": [],
        "fixed": [],
        "flaky": ["test_a"],
        "written": ["app.py", "requirements.txt"],
    }
    return {**document, **changed}


class World:
    """A checkout with a base commit that holds an executable, and the folder of an artifact."""

    def __init__(self, tmp_path: Path) -> None:
        self.repo = committed(tmp_path / "repo", FILES)
        plumb(self.repo, "update-index", "--chmod=+x", "tool.py")
        plumb(self.repo, "commit", "-qm", "executable")
        self.base = plumb(self.repo, "rev-parse", "HEAD")
        self.folder = tmp_path / "artifact" / "pydantic"
        self.folder.mkdir(parents=True)

    def bundle(self, *refs: str, base: str | None = None) -> None:
        """A bundle of `refs` that needs `base` (default the checkout's); `""` needs nothing."""
        target = str(self.folder / "upgrade.bundle")
        base = self.base if base is None else base
        plumb(self.repo, "bundle", "create", target, *refs, *([f"^{base}"] if base else []))

    def write(self, document: dict[str, Any] | str | None = None) -> None:
        text = document if isinstance(document, str) else json.dumps(document or trial())
        (self.folder / "trial.json").write_text(text, encoding="utf-8")

    def made(
        self,
        changes: Changes | None = None,
        *,
        branch: str = BRANCH,
        document: dict[str, Any] | None = None,
        **commit: Any,
    ) -> str:
        tip = craft(self.repo, branch, changes or EDIT, **commit)
        self.bundle(f"refs/heads/{branch}")
        self.write(document)
        return tip

    def check(self) -> Any:
        return upgrade.verified(self.folder, self.repo, self.base)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


# The privileged job: what it accepts.


def test_one_commit_on_the_base_that_the_trial_describes_is_accepted(world: World) -> None:
    tip = world.made()
    result = world.check()
    assert (result.branch, result.tip, result.title) == (BRANCH, tip, SUBJECT)
    assert "- `app.py`\n- `requirements.txt`" in result.body
    assert "12 test(s) passed before, 0 broke, 1 failed once and passed again" in result.body
    assert f"`{world.base[:10]}`" in result.body
    assert plumb(world.repo, "rev-parse", "refs/obelize-verify/pydantic") == tip


def test_what_the_commit_says_was_not_written_reaches_the_text_only_as_places(world: World) -> None:
    world.made(text=message(held="requirements.txt:1, sub/requirements.txt:3"))
    assert (
        "Not written, for you to change: the dependency line at "
        "`requirements.txt:1`, `sub/requirements.txt:3`."
    ) in world.check().body
    world.made(text=message(held="x`y:1"), branch="obelize/upgrade-pydantic-2.12.6")
    assert "Not written" not in world.check().body


def test_an_executable_a_move_edits_keeps_the_mode_it_had(world: World) -> None:
    edit: Changes = {"tool.py": ("100755", b"#!/usr/bin/env python\ny = 2\n")}
    world.made(edit, document=trial(written=["tool.py"]))
    assert world.check().tip


def test_more_files_than_the_listing_shows_are_counted(world: World) -> None:
    paths = [f"pkg/m{number:02}.py" for number in range(upgrade.LISTED + 3)]
    world.made(dict.fromkeys(paths, ("100644", b"x\n")), document=trial(written=paths))
    body = world.check().body
    assert "changes 53 file(s)" in body
    assert "- and 3 more" in body
    assert "pkg/m49.py" in body
    assert "pkg/m50.py" not in body


def test_the_paths_obelize_writes_are_sources_and_the_manifests_it_reads(world: World) -> None:
    paths = [
        "requirements/base.txt",
        "dev-requirements.txt",
        "pkg/types.pyi",
        "sub/setup.cfg",
        "Pipfile",
        "pyproject.toml",
        "setup.py",
        "dir with space/é.py",
    ]
    world.made(dict.fromkeys(paths, ("100644", b"x\n")), document=trial(written=paths))
    assert world.check().tip


# What it refuses.

NOT_PUBLISHED = "not a path this action publishes"
NO_SUCH_FILE = "writes no file of this kind"


@pytest.mark.parametrize(
    ("path", "says"),
    [
        (".github/workflows/ci.yml", NOT_PUBLISHED),
        (".GitHub/scripts/x.py", NOT_PUBLISHED),
        (".gitmodules", NOT_PUBLISHED),
        (".gitattributes", NOT_PUBLISHED),
        (".githooks/pre-push.py", NOT_PUBLISHED),
        (".obelize/trials/x/trial.json", NOT_PUBLISHED),
        ("a`b.py", NOT_PUBLISHED),
        pytest.param("a\\b.py", NOT_PUBLISHED, marks=NOT_ON_WINDOWS),
        pytest.param("a\nb.py", NOT_PUBLISHED, marks=NOT_ON_WINDOWS),
        pytest.param("a\tb.py", NOT_PUBLISHED, marks=NOT_ON_WINDOWS),
        ("README.md", NO_SUCH_FILE),
        ("Makefile", NO_SUCH_FILE),
        ("data/constraints.txt", NO_SUCH_FILE),
        ("requirements.in", NO_SUCH_FILE),
        ("src/app.pyc", NO_SUCH_FILE),
        ("notes.txt", NO_SUCH_FILE),
    ],
)
def test_a_path_obelize_does_not_write_is_refused_though_the_trial_names_it(
    world: World, path: str, says: str
) -> None:
    world.made({path: ("100644", b"x\n")}, document=trial(written=[path]))
    with pytest.raises(upgrade.RefusedError, match=says):
        world.check()


@pytest.mark.parametrize("path", ["/etc/x.py", "../x.py", "a/../x.py", "./x.py", "a//x.py", "a/"])
def test_a_path_that_leaves_the_repository_is_refused_by_the_script_itself(path: str) -> None:
    """Git will not hold these in a tree, so the check is called on the text."""
    with pytest.raises(upgrade.RefusedError, match=NOT_PUBLISHED):
        upgrade.place(path)


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (("link.py", ("120000", b"app.py")), "mode 120000"),
        (("run.py", ("100755", b"x = 1\n")), "mode 100755"),
        (("tool.py", ("100644", b"y = 2\n")), "its mode changes from 100755 to 100644"),
        (("app.py", ("100755", b"x = 2\n")), "its mode changes from 100644 to 100755"),
        (("vendor.py", ("160000", b"")), "mode 160000"),
        (("app.py", None), "a change of kind D"),
    ],
    ids=[
        "a link",
        "an added executable",
        "a plain file",
        "an executable",
        "a submodule",
        "a deletion",
    ],
)
def test_a_link_an_executable_a_submodule_or_a_deletion_is_refused(
    world: World, change: tuple[str, tuple[str, bytes] | None], says: str
) -> None:
    path, entry = change
    if path == "vendor.py":
        entry = ("160000", world.base.encode())
    world.made({path: entry}, document=trial(written=[path]))
    with pytest.raises(upgrade.RefusedError, match=says):
        world.check()


def test_a_path_the_trial_does_not_name_is_refused(world: World) -> None:
    world.made({"app.py": ("100644", b"x = 2\n"), "other.py": ("100644", b"y = 2\n")})
    with pytest.raises(upgrade.RefusedError, match=r"other\.py: the trial does not name it"):
        world.check()


def test_a_commit_that_changes_nothing_is_refused(world: World) -> None:
    world.made({"app.py": ("100644", b"x = 1\n")})
    with pytest.raises(upgrade.RefusedError, match="changes 0 files"):
        world.check()


def test_more_files_or_a_bigger_file_than_the_limits_are_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.made()
    monkeypatch.setattr(upgrade, "MAX_FILES", 1)
    with pytest.raises(upgrade.RefusedError, match="changes 2 files"):
        world.check()
    monkeypatch.setattr(upgrade, "MAX_FILES", 10)
    monkeypatch.setattr(upgrade, "MAX_BLOB", 5)
    with pytest.raises(upgrade.RefusedError, match="more than 5 bytes"):
        world.check()


def test_a_tree_with_an_entry_called_dot_git_is_refused_though_git_would_hold_it(
    world: World,
) -> None:
    """`git update-index` will not make one, but a tree object can be written by hand, and fetching
    a bundle does not stop it (`fetch.fsckObjects` passes it): the path rule does."""
    blob = plumb(world.repo, "hash-object", "-w", "--stdin", data=b"x\n")
    listing = plumb(world.repo, "ls-tree", world.base) + f"\n100644 blob {blob}\t.git"
    tree = plumb(world.repo, "mktree", data=(listing + "\n").encode())
    env = {
        "GIT_AUTHOR_NAME": IDENTITY[0],
        "GIT_AUTHOR_EMAIL": IDENTITY[1],
        "GIT_COMMITTER_NAME": IDENTITY[0],
        "GIT_COMMITTER_EMAIL": IDENTITY[1],
    }
    made = plumb(world.repo, "commit-tree", tree, "-p", world.base, "-m", message(), env=env)
    plumb(world.repo, "update-ref", f"refs/heads/{BRANCH}", made)
    world.bundle(f"refs/heads/{BRANCH}")
    world.write(trial(written=[".git"]))
    with pytest.raises(upgrade.RefusedError, match=NOT_PUBLISHED):
        world.check()


def test_a_bundle_with_a_second_branch_or_a_tag_is_refused(world: World) -> None:
    world.made()
    craft(world.repo, "obelize/upgrade-other-1.0", {"app.py": ("100644", b"x = 3\n")})
    world.bundle(f"refs/heads/{BRANCH}", "refs/heads/obelize/upgrade-other-1.0")
    with pytest.raises(upgrade.RefusedError, match="one branch of obelize/upgrade-"):
        world.check()
    plumb(world.repo, "tag", "v1", plumb(world.repo, "rev-parse", "obelize/upgrade-other-1.0"))
    world.bundle("refs/tags/v1")
    with pytest.raises(upgrade.RefusedError, match="one branch of obelize/upgrade-"):
        world.check()


@pytest.mark.parametrize(
    "branch",
    ["obelize/other", "obelize/upgrade-", "obelize/upgrade-Bad", "obelize/upgrade--x", "main"],
)
def test_a_branch_the_cli_would_not_have_named_is_refused(world: World, branch: str) -> None:
    craft(world.repo, branch, {"app.py": ("100644", b"x = 2\n")})
    world.write()
    world.bundle(f"refs/heads/{branch}")
    with pytest.raises(upgrade.RefusedError, match=r"one branch of obelize/upgrade-|git "):
        world.check()


def test_a_commit_on_another_base_is_refused(world: World) -> None:
    older = plumb(world.repo, "rev-parse", "HEAD~1")
    craft(world.repo, BRANCH, {"app.py": ("100644", b"x = 2\n")}, parent=older)
    world.bundle(f"refs/heads/{BRANCH}", base=older)
    world.write()
    with pytest.raises(upgrade.RefusedError, match="one commit on the commit the job ran on"):
        world.check()


def test_a_bundle_that_needs_a_commit_the_checkout_lacks_is_refused(
    world: World, tmp_path: Path
) -> None:
    other = committed(tmp_path / "other", {"app.py": "x = 9\n"})
    craft(other, BRANCH, {"app.py": ("100644", b"x = 2\n")})
    target = str(world.folder / "upgrade.bundle")
    plumb(other, "bundle", "create", target, f"refs/heads/{BRANCH}", f"^{BRANCH}~1")
    world.write()
    with pytest.raises(upgrade.RefusedError, match="git bundle"):
        world.check()


def test_two_commits_are_not_one_commit_on_the_base(world: World) -> None:
    first = craft(world.repo, BRANCH, {"app.py": ("100644", b"x = 2\n")})
    craft(world.repo, BRANCH, {"app.py": ("100644", b"x = 3\n")}, parent=first)
    world.bundle(f"refs/heads/{BRANCH}")
    world.write()
    with pytest.raises(upgrade.RefusedError, match="one commit on the commit the job ran on"):
        world.check()


@pytest.mark.parametrize(
    "who",
    [
        ("someone", "someone@example.com"),
        ("obelize", "other@example.com"),
        ("Obelize", IDENTITY[1]),
    ],
)
def test_a_commit_by_another_identity_is_refused(world: World, who: tuple[str, str]) -> None:
    world.made(who=who)
    with pytest.raises(upgrade.RefusedError, match="identity the action gives it"):
        world.check()


@pytest.mark.parametrize(
    "text",
    [
        message("Upgrade pydantic 1.10.25 to pydantic>=2.12.5,<3"),
        message("Upgrade pydantic 1.10.26 to pydantic>=2.12.6,<3"),
        message("Upgrade other 1.10.26 to pydantic>=2.12.5,<3"),
        message("Upgrade pydantic 1.10.26 to pydantic>=2.12.5,<3 now"),
        "Fix things\n",
        "no subject\n",
    ],
)
def test_a_subject_that_does_not_name_the_upgrade_the_trial_describes_is_refused(
    world: World, text: str
) -> None:
    world.made(text=text)
    with pytest.raises(upgrade.RefusedError, match="subject does not name the upgrade"):
        world.check()


@pytest.mark.parametrize(
    ("document", "says"),
    [
        (trial(status="fail"), "the trial says 'fail'"),
        (trial(status=None), "the trial says 'None'"),
        (trial(distribution="other"), "the trial is about other"),
        (trial(distribution="py dantic"), "distribution is not a value"),
        (trial(distribution=3), "distribution is not a value"),
        (trial(**{"from": "1 2"}), "from is not a value"),
        (trial(to="x\ny"), "to is not a value"),
        (trial(written="app.py"), "written is not a list of strings"),
        (trial(written=["app.py", 3]), "written is not a list of strings"),
        (trial(compared=-1), "compared is not a count"),
        (trial(compared=True), "compared is not a count"),
        (trial(compared="12"), "compared is not a count"),
        (trial(broken="x"), "broken is not a list of strings"),
        (trial(flaky=None), "flaky is not a list of strings"),
    ],
)
def test_a_trial_that_is_no_pass_of_this_dependency_in_values_the_script_reads_is_refused(
    world: World, document: dict[str, Any], says: str
) -> None:
    world.made(document=document)
    with pytest.raises(upgrade.RefusedError, match=says):
        world.check()


@pytest.mark.parametrize("text", ["", "not json", "[]", "3", '{"a": ' * 5000])
def test_a_trial_that_is_not_a_json_object_is_refused(world: World, text: str) -> None:
    world.made()
    world.write(text)
    with pytest.raises(upgrade.RefusedError, match=r"trial\.json"):
        world.check()


def test_a_file_that_is_missing_or_too_big_is_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.made()
    (world.folder / "trial.json").unlink()
    with pytest.raises(upgrade.RefusedError, match=r"trial\.json is missing"):
        world.check()
    world.write()
    monkeypatch.setattr(upgrade, "MAX_REPORT", 10)
    with pytest.raises(upgrade.RefusedError, match="is too big"):
        world.check()
    monkeypatch.setattr(upgrade, "MAX_REPORT", 1 << 20)
    monkeypatch.setattr(upgrade, "MAX_BUNDLE", 10)
    with pytest.raises(upgrade.RefusedError, match=r"upgrade\.bundle is missing"):
        world.check()
    monkeypatch.setattr(upgrade, "MAX_BUNDLE", 1 << 20)
    (world.folder / "upgrade.bundle").unlink()
    with pytest.raises(upgrade.RefusedError, match=r"upgrade\.bundle is missing"):
        world.check()


@NEEDS_SH
def test_a_symbolic_link_stands_for_neither_file(world: World, tmp_path: Path) -> None:
    world.made()
    aside = tmp_path / "aside"
    aside.mkdir()
    for name in ("trial.json", "upgrade.bundle"):
        shutil.move(world.folder / name, aside / name)
        (world.folder / name).symlink_to(aside / name)
        with pytest.raises(upgrade.RefusedError, match="is missing"):
            world.check()
        (world.folder / name).unlink()
        shutil.move(aside / name, world.folder / name)
    assert world.check().tip


def test_bytes_that_are_not_a_bundle_are_refused(world: World) -> None:
    world.made()
    (world.folder / "upgrade.bundle").write_bytes(b"# v2 git bundle\nnot really\n")
    with pytest.raises(upgrade.RefusedError, match="git bundle"):
        world.check()


@pytest.mark.parametrize("name", ["Pydantic", "py_dantic", "-x", "a b", "a..b", ".hidden"])
def test_a_folder_this_action_would_not_have_made_is_refused(world: World, name: str) -> None:
    world.made()
    odd = world.folder.parent / name
    world.folder.rename(odd)
    with pytest.raises(upgrade.RefusedError, match="is not a folder this action makes"):
        upgrade.verified(odd, world.repo, world.base)


# The privileged job: pushing and the pull request.

GH = """#!/bin/sh
printf '%s\\n' "$@" > "$RECORD.args"
while [ $# -gt 0 ]; do
  [ "$1" = --body-file ] && cat "$2" > "$RECORD.body"
  shift
done
echo called >> "$RECORD.calls"
exit "$GH_EXIT"
"""


class Remote:
    """A bare repository as `origin`, and a `gh` that writes down what it was asked."""

    def __init__(self, world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.world = world
        self.bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.bare)], check=True)
        plumb(world.repo, "remote", "add", "origin", str(self.bare))
        plumb(world.repo, "push", "-q", "origin", "HEAD:refs/heads/work")
        self.record = tmp_path / "gh"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        script = bin_dir / "gh"
        script.write_text(GH, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("RECORD", str(self.record))
        monkeypatch.setenv("GH_EXIT", "0")

    def calls(self) -> int:
        path = Path(f"{self.record}.calls")
        return len(path.read_text().splitlines()) if path.exists() else 0

    def branches(self) -> list[str]:
        out = plumb(self.bare, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
        return sorted(out.split())

    def publish(self, branch: str = "main") -> int:
        code: int = upgrade.publish(
            self.world.folder.parent, self.world.repo, self.world.base, branch
        )
        return code


@pytest.fixture
def remote(world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Remote:
    return Remote(world, tmp_path, monkeypatch)


@NEEDS_SH
def test_a_verified_branch_is_pushed_and_a_pull_request_is_opened_for_it(
    remote: Remote, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    tip = world.made()
    assert remote.publish("work") == 0
    assert remote.branches() == [BRANCH, "work"]
    assert plumb(remote.bare, "rev-parse", BRANCH) == tip
    args = Path(f"{remote.record}.args").read_text().splitlines()
    assert args[:8] == ["pr", "create", "--head", BRANCH, "--base", "work", "--title", SUBJECT]
    assert args[8] == "--body-file"
    assert "opened a pull request" in capsys.readouterr().out
    assert plumb(world.repo, "for-each-ref", "refs/obelize-verify/") == ""
    assert Path(f"{remote.record}.body").read_text() == world.check().body


@NEEDS_SH
def test_a_branch_on_the_remote_is_not_touched_and_no_second_request_is_made(
    remote: Remote, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.made()
    assert remote.publish() == 0
    capsys.readouterr()
    assert remote.publish() == 0
    assert "exists on origin already, so it was not touched" in capsys.readouterr().out
    assert remote.calls() == 1


@NEEDS_SH
def test_a_folder_that_fails_does_not_stop_the_next_and_the_run_fails(
    remote: Remote, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.made()
    bad = world.folder.parent / "attrs"
    bad.mkdir()
    (bad / "trial.json").write_text("{}", encoding="utf-8")
    assert remote.publish() == 1
    assert "::error::attrs: the trial says 'None'" in capsys.readouterr().out
    assert remote.branches() == [BRANCH, "work"]
    assert remote.calls() == 1


@NEEDS_SH
def test_a_refused_folder_pushes_nothing(remote: Remote, world: World) -> None:
    flow = ".github/workflows/ci.yml"
    world.made({flow: ("100644", b"on: push\n")}, document=trial(written=[flow]))
    assert remote.publish() == 1
    assert remote.branches() == ["work"]
    assert remote.calls() == 0
    assert plumb(world.repo, "for-each-ref", "refs/obelize-verify/") == ""


@NEEDS_SH
def test_what_the_artifact_names_cannot_end_a_workflow_command_in_the_log(
    remote: Remote, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    odd = "a\n::notice::injected.md"
    world.made({odd: ("100644", b"x\n")}, document=trial(written=[odd]))
    (world.folder.parent / "x\n::notice::injected").mkdir()
    assert remote.publish() == 1
    lines = capsys.readouterr().out.splitlines()
    assert [line for line in lines if "injected" in line and not line.startswith("::error::")] == []
    assert not any(line.startswith("::notice::") for line in lines)
    assert any("%0A::notice::injected" in line for line in lines)


@NEEDS_SH
def test_a_pull_request_that_cannot_be_opened_is_said_and_the_branch_stays_pushed(
    remote: Remote,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    world.made()
    monkeypatch.setenv("GH_EXIT", "1")
    assert remote.publish() == 1
    assert f"gh pr create exited 1; {BRANCH} is pushed" in capsys.readouterr().out
    assert BRANCH in remote.branches()


def test_an_artifact_with_no_folder_is_nothing_to_do(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert upgrade.publish(empty, world.repo, world.base, "main") == 0
    assert "the artifact holds no upgrade" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("base", "branch", "says"),
    [
        ("abc", "main", "base takes a commit"),
        ("0" * 40, "-x", "base-branch takes a branch name"),
        ("0" * 40, "a b", "base-branch takes a branch name"),
        ("0" * 40, "", "base-branch takes a branch name"),
    ],
)
def test_a_base_or_a_branch_that_is_not_one_stops_before_anything_is_read(
    world: World, capsys: pytest.CaptureFixture[str], base: str, branch: str, says: str
) -> None:
    assert upgrade.publish(world.folder.parent, world.repo, base, branch) == 2
    assert says in capsys.readouterr().out


@NEEDS_SH
def test_a_symbolic_link_for_a_folder_is_not_one(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    aside = tmp_path / "aside"
    aside.mkdir()
    world.folder.rmdir()
    (world.folder.parent / "linked").symlink_to(aside)
    assert upgrade.publish(world.folder.parent, world.repo, world.base, "main") == 0
    assert "the artifact holds no upgrade" in capsys.readouterr().out


# The unprivileged job.

FAKE = """#!/bin/sh
printf '%s\\n' "$@" >> "$RECORD"
printf 'author=%s committer=%s\\n' "$GIT_AUTHOR_EMAIL" "$GIT_COMMITTER_NAME" >> "$RECORD"
code=0
for pair in $CODES; do [ "${pair%%=*}" = "$3" ] && code=${pair#*=}; done
[ "$code" = 0 ] || exit "$code"
[ -n "$NO_BRANCH" ] && exit 0
name=$(printf '%s' "$3" | tr 'A-Z_.' 'a-z--')
index=$(mktemp -d)/index
blob=$(printf 'x = 2\\n' | git hash-object -w --stdin)
GIT_INDEX_FILE=$index git read-tree HEAD
GIT_INDEX_FILE=$index git update-index --add --cacheinfo "100644,$blob,app.py"
tree=$(GIT_INDEX_FILE=$index git write-tree)
commit=$(git commit-tree "$tree" -p HEAD -m "Upgrade $3 1.0 to $3==2.0

Obelize-Trial: t1")
git update-ref "refs/heads/obelize/upgrade-$name-2.0" "$commit"
[ -n "$TWO_BRANCHES" ] && git update-ref "refs/heads/obelize/upgrade-$name-2.1" "$commit"
mkdir -p .obelize/trials/t1
printf '{"distribution":"%s","from":"1.0","to":"%s==2.0","status":"pass","compared":3,' "$3" "$3" \\
  > .obelize/trials/t1/trial.json
printf '"broken":[],"flaky":[],"written":["app.py"]}' >> .obelize/trials/t1/trial.json
printf 'pydantic==1.0\\n' > .obelize/trials/t1/old.txt
exit 0
"""


class Job:
    """The upgrade step on a checkout, with a `uvx` that makes a branch the way obelize does."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.repo = committed(tmp_path / "repo", {"app.py": "x = 1\n"})
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        uvx = bin_dir / "uvx"
        uvx.write_text(FAKE, encoding="utf-8")
        uvx.chmod(uvx.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("RECORD", str(tmp_path / "record"))
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_EVENT_NAME", "NO_BRANCH", "TWO_BRANCHES"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("CODES", "")
        self.out = tmp_path / "out"
        self.output = tmp_path / "output"
        self.summary = tmp_path / "summary"

    def env(self, **more: str) -> dict[str, str]:
        return {
            **os.environ,
            "OBELIZE_VERSION": "0.9.0",
            "OBELIZE_DISTRIBUTIONS": "pydantic",
            "OBELIZE_WORKDIR": str(self.repo),
            "OBELIZE_OUT": str(self.out),
            "GITHUB_OUTPUT": str(self.output),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            **more,
        }

    def run(self, **more: str) -> int:
        code: int = upgrade.run(self.env(**more))
        return code

    def outputs(self) -> dict[str, str]:
        lines = self.output.read_text(encoding="utf-8").splitlines() if self.output.exists() else []
        return dict(line.split("=", 1) for line in lines)

    def record(self) -> list[str]:
        return (self.tmp / "record").read_text(encoding="utf-8").splitlines()


@pytest.fixture
def job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Job:
    return Job(tmp_path, monkeypatch)


@NEEDS_SH
def test_each_dependency_is_upgraded_to_a_branch_bundled_with_its_patch_and_evidence(
    job: Job,
) -> None:
    assert job.run(OBELIZE_DISTRIBUTIONS="pydantic Django_Rest") == 0
    who = "author=obelize@users.noreply.github.com committer=obelize"
    flags = ("--apply", "--yes", "--branch")
    assert job.record() == [
        *("obelize==0.9.0", "upgrade", "pydantic", *flags, who),
        *("obelize==0.9.0", "upgrade", "Django_Rest", *flags, who),
    ]
    assert sorted(path.name for path in job.out.iterdir()) == ["django-rest", "pydantic"]
    folder = job.out / "pydantic"
    names = ["REPORT.md", "old.txt", "trial.json", "upgrade.bundle", "upgrade.patch"]
    assert sorted(path.name for path in folder.iterdir()) == names
    assert "+x = 2" in (folder / "upgrade.patch").read_text()
    report = (folder / "REPORT.md").read_text()
    assert "pydantic 1.0 to pydantic==2.0: pass; 3 test(s) passed before, 0 broke" in report
    outputs = job.outputs()
    assert (outputs["exit-code"], outputs["changed"], outputs["out-dir"]) == (
        "0",
        "true",
        str(job.out),
    )
    assert outputs["bundle-file"].split() == [
        str(job.out / "pydantic" / "upgrade.bundle"),
        str(job.out / "django-rest" / "upgrade.bundle"),
    ]
    assert outputs["report-file"].split()[0] == str(folder / "REPORT.md")
    assert "| `pydantic` | 0 | `obelize/upgrade-pydantic-2.0` |" in job.summary.read_text()


@NEEDS_SH
def test_the_release_the_code_is_written_for_goes_to_the_command_for_one_dependency(
    job: Job,
) -> None:
    assert job.run(OBELIZE_FROM="1.10.26") == 0
    assert job.record()[6:8] == ["--from", "1.10.26"]


@NEEDS_SH
@pytest.mark.parametrize("code", [1, 2, 3, 4, 6])
def test_an_upgrade_that_did_not_succeed_makes_no_folder_and_its_code_is_the_output(
    job: Job, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    monkeypatch.setenv("CODES", f"pydantic={code}")
    assert job.run() == 0
    assert job.outputs() == {
        "exit-code": str(code),
        "changed": "false",
        "bundle-file": "",
        "report-file": "",
        "out-dir": "",
    }
    assert not job.out.exists()


@NEEDS_SH
def test_the_first_dependency_that_did_not_succeed_gives_the_code_and_the_others_go_on(
    job: Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODES", "pydantic=6 attrs=0")
    assert job.run(OBELIZE_DISTRIBUTIONS="pydantic attrs") == 0
    outputs = job.outputs()
    assert (outputs["exit-code"], outputs["changed"]) == ("6", "true")
    assert [path.name for path in job.out.iterdir()] == ["attrs"]


@NEEDS_SH
def test_an_upgrade_that_exits_zero_with_no_branch_is_an_error_and_not_a_pass(
    job: Job, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NO_BRANCH", "1")
    assert job.run() == 0
    assert job.outputs()["exit-code"] == "1"
    assert "exited 0 and left no one branch to publish" in capsys.readouterr().out


@NEEDS_SH
def test_an_upgrade_that_leaves_two_branches_is_not_published(
    job: Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TWO_BRANCHES", "1")
    assert job.run() == 0
    assert (job.outputs()["exit-code"], job.outputs()["changed"]) == ("1", "false")


BAD = [
    ({"GITHUB_EVENT_NAME": "pull_request_target"}, "never on pull_request_target"),
    ({"GH_TOKEN": "x"}, "GH_TOKEN is set"),
    ({"GITHUB_TOKEN": "x"}, "GITHUB_TOKEN is set"),
    ({"OBELIZE_VERSION": ""}, "version takes a release"),
    ({"OBELIZE_VERSION": "latest"}, "version takes a release"),
    ({"OBELIZE_VERSION": "0.9.0 --index-url=https://x"}, "version takes a release"),
    ({"OBELIZE_DISTRIBUTIONS": ""}, "distributions takes the dependencies"),
    ({"OBELIZE_DISTRIBUTIONS": "  "}, "distributions takes the dependencies"),
    (
        {"OBELIZE_DISTRIBUTIONS": " ".join(f"d{n}" for n in range(21))},
        "distributions takes the dep",
    ),
    ({"OBELIZE_DISTRIBUTIONS": "--pack"}, "distributions takes distribution names"),
    ({"OBELIZE_DISTRIBUTIONS": "a;b"}, "distributions takes distribution names"),
    ({"OBELIZE_DISTRIBUTIONS": "$(id)"}, "distributions takes distribution names"),
    ({"OBELIZE_DISTRIBUTIONS": "pydantic Pydantic"}, "names one dependency twice"),
    ({"OBELIZE_DISTRIBUTIONS": "a_b a.b"}, "names one dependency twice"),
    ({"OBELIZE_FROM": "latest"}, "from takes a release"),
    ({"OBELIZE_FROM": "1.0", "OBELIZE_DISTRIBUTIONS": "a b"}, "from goes with one distribution"),
    ({"OBELIZE_ARTIFACT_NAME": "a b"}, "artifact-name takes letters"),
    ({"OBELIZE_ARTIFACT_NAME": "a/b"}, "artifact-name takes letters"),
    ({"OBELIZE_WORKDIR": "/nonexistent-obelize"}, "is not a directory"),
]


@NEEDS_SH
@pytest.mark.parametrize(("env", "says"), BAD)
def test_a_value_that_could_become_a_flag_a_command_or_a_token_in_the_job_stops_it(
    job: Job, capsys: pytest.CaptureFixture[str], env: dict[str, str], says: str
) -> None:
    assert job.run(**env) == 2
    assert says in capsys.readouterr().out
    assert not (job.tmp / "record").exists()
    assert not job.out.exists()


@NEEDS_SH
def test_a_folder_that_holds_something_or_a_directory_that_is_no_checkout_stops_it(
    job: Job, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job.out.mkdir()
    (job.out / "left").write_text("x")
    assert job.run() == 2
    assert "holds files already" in capsys.readouterr().out
    plain = tmp_path / "plain"
    plain.mkdir()
    assert job.run(OBELIZE_WORKDIR=str(plain), OBELIZE_OUT=str(tmp_path / "other")) == 2
    assert "is not a git checkout with a commit" in capsys.readouterr().out
    assert not (job.tmp / "record").exists()


@NEEDS_SH
def test_the_step_may_run_with_no_output_or_summary_file(job: Job) -> None:
    env = job.env()
    del env["GITHUB_OUTPUT"], env["GITHUB_STEP_SUMMARY"]
    assert upgrade.run(env) == 0
    assert (job.out / "pydantic" / "upgrade.bundle").is_file()


def test_a_report_says_so_when_the_trial_left_nothing_it_could_read(tmp_path: Path) -> None:
    assert "left no evidence this report could read" in upgrade.report(tmp_path, "msg\n")
    (tmp_path / "trial.json").write_text('{"distribution": "x"}', encoding="utf-8")
    assert "left no evidence" in upgrade.report(tmp_path, "msg\n")


# The verdict.


@pytest.mark.parametrize(
    ("code", "strict", "result"),
    [
        ("0", "false", 0),
        ("0", "true", 0),
        ("3", "false", 0),
        ("4", "false", 0),
        ("6", "false", 0),
        ("3", "true", 3),
        ("4", "true", 4),
        ("6", "true", 6),
        ("2", "false", 2),
        ("5", "false", 5),
        ("1", "false", 1),
        ("7", "false", 7),
        ("", "false", 1),
        ("x", "false", 1),
        ("-3", "false", 1),
        ("3", "yes", 2),
        ("3", "", 2),
    ],
)
def test_the_verdict_fails_a_mistake_always_and_an_unproven_move_only_when_asked(
    code: str, strict: str, result: int
) -> None:
    env = {"OBELIZE_EXIT_CODE": code, "OBELIZE_FAIL_ON_UNPROVEN": strict}
    assert upgrade.gate(env) == result


def test_the_codes_that_pass_unless_asked_are_ones_the_cli_documents() -> None:
    text = (ROOT / "docs" / "CLI.md").read_text(encoding="utf-8")
    assert {3, 4, 6} == upgrade.UNPROVEN
    for code in upgrade.UNPROVEN:
        assert f"| `{code}` |" in text


# The command line.


def test_the_script_takes_a_command_and_each_command_is_run(world: World, tmp_path: Path) -> None:
    script = str(ROOT / "action" / "upgrade.py")
    env = {**os.environ, "OBELIZE_EXIT_CODE": "0", "OBELIZE_FAIL_ON_UNPROVEN": "false"}
    assert subprocess.run([sys.executable, script, "gate"], env=env, check=False).returncode == 0
    empty = tmp_path / "none"
    empty.mkdir()
    publish = [script, "publish", "--artifacts", str(empty), "--repo", str(world.repo)]
    publish += ["--base", world.base, "--base-branch", "main"]
    assert subprocess.run([sys.executable, *publish], check=False).returncode == 0
    nothing = subprocess.run([sys.executable, script], capture_output=True, check=False)
    assert nothing.returncode == 2


def test_the_manifests_the_script_publishes_are_the_ones_obelize_reads() -> None:
    from obelize.scan import manifests

    assert set(manifests.NAMES) == upgrade.MANIFESTS
    assert manifests.REQUIREMENTS_GLOB == "*requirement*.txt"
    assert manifests.REQUIREMENTS_DIRECTORY == "requirements"


def test_the_branch_the_script_expects_is_the_one_the_cli_makes() -> None:
    from obelize import cli

    for install in ("pydantic==2.12.5", "pypdf>=6.19,<7", "Acme_Kit==2.0", "openai>=1.109.1"):
        assert upgrade.BRANCH.fullmatch(cli._branch_name(install)), install
