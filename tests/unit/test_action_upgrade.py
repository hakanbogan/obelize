"""The upgrade mode of the action (`action/upgrade.py`): the job that runs the tests, the verdict on
its exit codes, and the job that may write to the repository and checks what it is handed.

Everything the second job reads is forged in these tests with git's plumbing, because everything it
reads came from a job that ran code the second job does not trust. The forging is done in one
repository and the checking in a depth-1 clone of it that lacks the forged objects, as in a job
that checked the repository out: a check run where the objects already exist fetches nothing.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
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
TITLE = f"Upgrade pydantic {OLD} to {NEW}"
FILES = {
    "app.py": "x = 1\n",
    "tool.py": "#!/usr/bin/env python\ny = 1\n",
    "requirements.txt": "pydantic==1.10.26\n",
    "README.md": "hi\n",
    "requirements/base.txt": "pydantic==1.10.26\n",
    "dev-requirements.txt": "pydantic==1.10.26\n",
    "pkg/types.pyi": "x: int\n",
    "pkg/conftest.py": "x = 1\n",
    "pkg/setup.py": "x = 1\n",
    "sub/setup.cfg": "[options]\n",
    "Pipfile": "[packages]\n",
    "pyproject.toml": "[project]\n",
    "dir with space/é.py": "x = 1\n",
}
Changes = dict[str, tuple[str, bytes] | None]
EDIT: Changes = {"app.py": ("100644", b"x = 2\n"), "requirements.txt": ("100644", b"pydantic>=2\n")}


def message(*, held: str = "") -> str:
    return (
        f"{TITLE}\n\nobelize 0.9.0 moved the code with the pack acme/x.\n"
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


def who(name: str, email: str) -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }


def craft(
    root: Path,
    branch: str,
    changes: Changes,
    *,
    text: str | None = None,
    parent: str | None = None,
    by: tuple[str, str] = IDENTITY,
) -> str:
    """A commit on `parent` (default `HEAD`) that sets each path to `(mode, bytes)` or removes it,
    pointed at by `refs/heads/<branch>`. A gitlink's bytes are the commit it names."""
    parent = parent or plumb(root, "rev-parse", "HEAD")
    with tempfile.TemporaryDirectory() as folder:
        env = {"GIT_INDEX_FILE": str(Path(folder) / "index"), **who(*by)}
        plumb(root, "read-tree", parent, env=env)
        for path, entry in changes.items():
            if entry is None:
                plumb(root, "update-index", "--force-remove", path, env=env)
                continue
            mode, data = entry
            blob = (
                data.decode()
                if mode == "160000"
                else plumb(root, "hash-object", "-w", "--stdin", data=data)
            )
            plumb(root, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}", env=env)
        tree = plumb(root, "write-tree", env=env)
        body = (text or message()).encode()
        made = plumb(root, "commit-tree", tree, "-p", parent, env=env, data=body)
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
    """A repository to forge in, a depth-1 clone to check in, and the folders of an artifact."""

    def __init__(self, tmp_path: Path, files: dict[str, str] | None = None) -> None:
        self.repo = committed(tmp_path / "repo", files or FILES)
        plumb(self.repo, "update-index", "--chmod=+x", "tool.py")
        plumb(self.repo, "commit", "-qm", "executable")
        self.base = plumb(self.repo, "rev-parse", "HEAD")
        self.checkout = tmp_path / "checkout"
        url = f"file://{self.repo}"
        subprocess.run(
            ["git", "clone", "-q", "--no-local", "--depth", "1", url, str(self.checkout)],
            check=True,
        )
        self.artifacts = tmp_path / "artifact"
        self.folder = self.of("pydantic")

    def of(self, name: str) -> Path:
        path = self.artifacts / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def bundle(self, *refs: str, base: str | None = None, name: str = "pydantic") -> None:
        """A bundle of `refs` that needs `base` (default the checkout's); `""` needs nothing."""
        base = self.base if base is None else base
        target = str(self.of(name) / "upgrade.bundle")
        plumb(self.repo, "bundle", "create", target, *refs, *([f"^{base}"] if base else []))

    def write(self, document: dict[str, Any] | str | None = None, name: str = "pydantic") -> None:
        text = document if isinstance(document, str) else json.dumps(document or trial())
        (self.of(name) / "trial.json").write_text(text, encoding="utf-8")

    def made(
        self,
        changes: Changes | None = None,
        *,
        name: str = "pydantic",
        document: dict[str, Any] | None = None,
        **commit: Any,
    ) -> str:
        branch = f"obelize/upgrade-{name}-2.12.5"
        tip = craft(self.repo, branch, changes or EDIT, **commit)
        self.bundle(f"refs/heads/{branch}", name=name)
        self.write(document or trial(distribution=name), name)
        return tip

    def check(self, name: str = "pydantic") -> Any:
        return upgrade.verified(self.of(name), self.checkout, self.base)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def pushed(world: World, result: Any) -> str:
    """The commit a result would push, as git stores it."""
    return plumb(world.checkout, "cat-file", "commit", result.tip)


# The job that may write: what it accepts.


def test_the_commit_that_is_pushed_is_made_from_the_bundles_tree_on_the_base(world: World) -> None:
    tip = world.made()
    result = world.check()
    assert (result.branch, result.title) == ("obelize/upgrade-pydantic-2.12.5", TITLE)
    assert result.tip != tip
    assert plumb(world.checkout, "rev-parse", f"{result.tip}^") == world.base
    assert plumb(world.checkout, "rev-parse", f"{result.tip}^{{tree}}") == plumb(
        world.repo, "rev-parse", f"{tip}^{{tree}}"
    )
    assert "- `app.py`\n- `requirements.txt`" in result.body
    assert "12 test(s) passed before the move" in result.body
    assert "These counts are that job's claim" in result.body
    assert f"`{world.base[:10]}`" in result.body
    assert plumb(world.checkout, "rev-parse", "refs/obelize-verify/pydantic") == tip


def test_nothing_the_forged_commit_says_is_pushed(world: World) -> None:
    """Its message, its author, its extra headers and its size stay in the bundle."""
    text = (
        f"{TITLE}\n\nCo-authored-by: Linus Torvalds <torvalds@linux-foundation.org>\n"
        "@octocat please look\n" + "A" * 5_000_000 + "\n"
    )
    world.made(text=text, by=("Linus Torvalds", "torvalds@linux-foundation.org"))
    result = world.check()
    raw = pushed(world, result)
    header, _, body = raw.partition("\n\n")
    lines = header.split("\n")
    assert [line.split(" ", 1)[0] for line in lines] == ["tree", "parent", "author", "committer"]
    assert lines[2].startswith(f"author {IDENTITY[0]} <{IDENTITY[1]}> ")
    assert lines[3].startswith(f"committer {IDENTITY[0]} <{IDENTITY[1]}> ")
    assert body.startswith(f"{TITLE}\n\nThe job that ran the tests reports")
    assert len(raw) < 2000
    assert not any(word in raw for word in ("Linus", "octocat", "Co-authored"))


def test_the_extra_headers_of_a_forged_commit_are_not_pushed_either(world: World) -> None:
    tree = plumb(world.repo, "rev-parse", f"{world.base}^{{tree}}")
    blob = plumb(world.repo, "hash-object", "-w", "--stdin", data=b"x = 2\n")
    entries = plumb(world.repo, "ls-tree", tree)
    app = next(line for line in entries.split("\n") if line.endswith("\tapp.py"))
    tree = plumb(
        world.repo,
        "mktree",
        data=(entries.replace(app.split("\t")[0], f"100644 blob {blob}") + "\n").encode(),
    )
    author = f"{IDENTITY[0]} <{IDENTITY[1]}> 1700000000 +0000"
    raw = (
        f"tree {tree}\nparent {world.base}\nauthor {author}\ncommitter {author}\n"
        "encoding ISO-8859-1\ngpgsig -----BEGIN PGP SIGNATURE-----\n junk\n"
        " -----END PGP SIGNATURE-----\n"
        f"\n{TITLE}\n"
    )
    made = plumb(
        world.repo, "hash-object", "-t", "commit", "-w", "--stdin", "--literally", data=raw.encode()
    )
    plumb(world.repo, "update-ref", "refs/heads/obelize/upgrade-pydantic-2.12.5", made)
    world.bundle("refs/heads/obelize/upgrade-pydantic-2.12.5")
    world.write(trial(written=["app.py"]))
    result = world.check()
    header = pushed(world, result).partition("\n\n")[0]
    assert "gpgsig" not in header
    assert "encoding" not in header


def test_a_tree_written_with_a_mode_a_diff_reads_as_another_is_written_again(world: World) -> None:
    """A mode of 100664 is 100644 to `diff-tree` and stays 100664 in the object: the tree that is
    pushed is made here from the base and the verified edits, not taken from the bundle."""
    blob = plumb(world.repo, "hash-object", "-w", "--stdin", data=b"x = 2\n")
    raw = b""
    for entry in plumb(world.repo, "ls-tree", "-z", world.base).split("\0"):
        if not entry:
            continue
        meta, _, name = entry.partition("\t")
        mode, _, sha = meta.split(" ")
        if name == "app.py":
            mode, sha = "100664", blob
        raw += f"{mode.lstrip('0')} {name}".encode() + b"\0" + bytes.fromhex(sha)
    tree = plumb(world.repo, "hash-object", "-t", "tree", "-w", "--stdin", "--literally", data=raw)
    made = plumb(
        world.repo, "commit-tree", tree, "-p", world.base, "-m", message(), env=who(*IDENTITY)
    )
    branch = "obelize/upgrade-pydantic-2.12.5"
    plumb(world.repo, "update-ref", f"refs/heads/{branch}", made)
    world.bundle(f"refs/heads/{branch}")
    world.write(trial(written=["app.py"]))

    def stored(root: Path, sha: str) -> bytes:
        done = subprocess.run(
            ["git", "-C", str(root), "cat-file", "tree", sha], capture_output=True, check=True
        )
        return done.stdout

    assert b"100664 app.py" in stored(world.repo, tree)
    result = world.check()
    pushed_tree = plumb(world.checkout, "rev-parse", f"{result.tip}^{{tree}}")
    assert pushed_tree != tree
    assert b"100664" not in stored(world.checkout, pushed_tree)
    assert b"100644 app.py" in stored(world.checkout, pushed_tree)


def test_what_the_commit_says_was_not_written_reaches_the_text_only_as_places(world: World) -> None:
    world.made(text=message(held="requirements.txt:1, sub/requirements.txt:3"))
    result = world.check()
    line = (
        "Not written, for you to change: the dependency line at "
        "`requirements.txt:1`, `sub/requirements.txt:3`."
    )
    assert line in result.body
    assert line in pushed(world, result)
    world.made(text=message(held="x`y:1"), name="attrs")
    assert "Not written" not in world.check("attrs").body


def test_a_move_of_some_files_says_in_the_text_it_makes_which_files_were_left(world: World) -> None:
    world.made(document=trial(held=["pkg/b.py", "a.py"]))
    result = world.check()
    line = (
        "Left as they were, for you to change: `a.py`, `pkg/b.py`. A place in each is left for "
        "you, so this move is partial: the tests that passed before still pass, which does not "
        "show that the rest has moved."
    )
    assert line in result.body
    assert line in pushed(world, result)
    world.made(document=trial(distribution="attrs"), name="attrs")
    assert "Left as they were" not in world.check("attrs").body


def test_more_files_left_than_the_listing_shows_are_counted(world: World) -> None:
    left = [f"left{index:03}.py" for index in range(upgrade.LISTED + 3)]
    world.made(document=trial(held=left))
    assert f"`left{upgrade.LISTED - 1:03}.py`, and 3 more. A place" in world.check().body


@pytest.mark.parametrize(
    ("held", "says"),
    [
        ("a.py", "held is not a list of strings"),
        (["a.py", 3], "held is not a list of strings"),
        (["x`y.py"], "not text this action prints"),
        (["x\\y.py"], "not text this action prints"),
        (["x\ny.py"], "not text this action prints"),
        (["x\x85y.py"], "not text this action prints"),
        (["x\u2028y.py"], "not text this action prints"),
        (["x\u202ey.py"], "not text this action prints"),
        (["\ud800.py"], "not text this action prints"),
        ([""], "not text this action prints"),
        (["a" * (upgrade.MAX_NAME + 1)], "not text this action prints"),
    ],
    ids=[
        "string",
        "number",
        "backtick",
        "backslash",
        "newline",
        "next-line",
        "line-separator",
        "bidi-override",
        "lone-surrogate",
        "empty",
        "long",
    ],
)
def test_a_file_the_trial_says_was_left_is_text_the_script_would_print(
    world: World, held: object, says: str
) -> None:
    world.made(document=trial(held=held))
    with pytest.raises(upgrade.RefusedError, match=says):
        world.check()


# A name `place` would refuse is no reason to refuse a file that was not written: it is only text.
LEFT = {
    "colon": "tools/run:all.py",
    "short-name": "pkg/x~1.py",
    "precomposed": "caf\u00e9.py",
    "decomposed": "cafe\u0301.py",
    "fullwidth": "\uff54ools/a.py",
    "parent": "../a.py",
    "dot-github": ".github/x.py",
    "markdown": "notes.md",
    "space": "a b.py",
    "longest": "a" * upgrade.MAX_NAME,
}


def test_place_refuses_the_names_a_written_file_may_not_have() -> None:
    for name in (
        "colon",
        "short-name",
        "decomposed",
        "fullwidth",
        "parent",
        "dot-github",
        "markdown",
    ):
        with pytest.raises(
            upgrade.RefusedError, match=r"not a path this action publishes|obelize writes no file"
        ):
            upgrade.place(LEFT[name])


@pytest.mark.parametrize("name", LEFT.values(), ids=LEFT)
def test_a_file_left_as_it_was_is_named_whatever_place_would_make_of_the_name(
    world: World, name: str
) -> None:
    world.made(document=trial(held=[name]))
    result = world.check()
    assert f"Left as they were, for you to change: `{name}`." in result.body
    # git on macOS precomposes what it is handed, so the commit is compared as such.
    said = unicodedata.normalize("NFC", f"`{name}`. A place in each")
    assert said in unicodedata.normalize("NFC", pushed(world, result))


@NEEDS_SH
def test_a_name_that_place_refuses_does_not_stop_a_branch_that_was_written_whole_from_publishing(
    remote: Remote, world: World
) -> None:
    world.made(document=trial(held=["tools/run:all.py", "pkg/x~1.py"]))
    assert remote.publish("work") == 0
    assert remote.branches() == ["obelize/upgrade-pydantic-2.12.5", "work"]
    body = Path(f"{remote.record}.body").read_text()
    assert "Left as they were, for you to change: `pkg/x~1.py`, `tools/run:all.py`." in body


def test_an_executable_a_move_edits_keeps_the_mode_it_had(world: World) -> None:
    edit: Changes = {"tool.py": ("100755", b"#!/usr/bin/env python\ny = 2\n")}
    world.made(edit, document=trial(written=["tool.py"]))
    assert world.check().tip


def test_more_files_than_the_listing_shows_are_counted(tmp_path: Path) -> None:
    paths = [f"pkg/m{number:02}.py" for number in range(upgrade.LISTED + 3)]
    world = World(tmp_path, {**FILES, **dict.fromkeys(paths, "x = 1\n")})
    world.made(dict.fromkeys(paths, ("100644", b"x = 2\n")), document=trial(written=paths))
    body = world.check().body
    assert "changes 53 file(s)" in body
    assert "- and 3 more" in body
    assert "pkg/m49.py" in body
    assert "pkg/m50.py" not in body


def test_the_edits_obelize_makes_are_to_sources_and_the_manifests_it_reads(world: World) -> None:
    paths = [
        "requirements/base.txt",
        "dev-requirements.txt",
        "pkg/types.pyi",
        "sub/setup.cfg",
        "Pipfile",
        "pyproject.toml",
        "pkg/setup.py",
        "dir with space/é.py",
    ]
    world.made(dict.fromkeys(paths, ("100644", b"x\n")), document=trial(written=paths))
    assert world.check().tip


def test_an_edit_to_a_file_that_runs_later_is_accepted_because_a_rule_may_make_it(
    world: World,
) -> None:
    """The limit ADR-078 states: the reader of the pull request is the control for this."""
    world.made(
        {"pkg/conftest.py": ("100644", b"import os\n")}, document=trial(written=["pkg/conftest.py"])
    )
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
        pytest.param("x.py:stream.py", NOT_PUBLISHED, marks=NOT_ON_WINDOWS),
        ("GITHUB~1/workflows/x.py", NOT_PUBLISHED),
        ("a\u0085b.py", NOT_PUBLISHED),
        ("a\u2028b.py", NOT_PUBLISHED),
        ("a\u202eyp.txt.py", NOT_PUBLISHED),
        ("\uff0egit/x.py", NOT_PUBLISHED),
        ("a\u00a0b.py", NOT_PUBLISHED),
        pytest.param("a\\b.py", NOT_PUBLISHED, marks=NOT_ON_WINDOWS),
        pytest.param("a\nb.py", NOT_PUBLISHED, marks=NOT_ON_WINDOWS),
        pytest.param("a\tb.py", NOT_PUBLISHED, marks=NOT_ON_WINDOWS),
        pytest.param("a\udcffb.py", NOT_PUBLISHED, marks=NOT_ON_WINDOWS),
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


@pytest.mark.parametrize(
    "path",
    [
        "/etc/x.py",
        "../x.py",
        "a/../x.py",
        "./x.py",
        "a//x.py",
        "a/",
        ".git/x.py",
        "sub/.git/x.py",
        ".GIT/x.py",
        ".git /x.py",
        ".git./x.py",
        "git~1/x.py",
    ],
)
def test_a_path_git_would_not_hold_or_a_file_system_would_fold_is_refused_by_the_script(
    path: str,
) -> None:
    with pytest.raises(upgrade.RefusedError, match=NOT_PUBLISHED):
        upgrade.place(path)


@pytest.mark.parametrize(
    "path",
    [
        "conftest.py",
        "sitecustomize.py",
        "setup.py",
        "noxfile.py",
        "run_me.py",
        ".venv/lib/x.py",
        ".vscode/x.py",
        "requirements/evil.txt",
        "evil-requirement.txt",
        "pyproject.toml.py",
    ],
)
def test_a_file_that_is_new_is_refused_though_it_is_of_a_kind_obelize_writes(
    world: World, path: str
) -> None:
    """An upgrade edits files in place, so a bundle may only change files the base tree has."""
    world.made({path: ("100644", b"import os\n")}, document=trial(written=[path]))
    with pytest.raises(upgrade.RefusedError, match="a change of kind A"):
        world.check()


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (("app.py", ("120000", b"tool.py")), "a change of kind T"),
        (("app.py", ("160000", "")), "a change of kind T"),
        (("run.py", ("100755", b"x = 1\n")), "a change of kind A"),
        (("tool.py", ("100644", b"y = 2\n")), "mode 100755 to 100644"),
        (("app.py", ("100755", b"x = 2\n")), "mode 100644 to 100755"),
        (("app.py", None), "a change of kind D"),
    ],
    ids=[
        "a link",
        "a submodule",
        "an added executable",
        "a plain file",
        "an executable",
        "a deletion",
    ],
)
def test_a_link_an_executable_a_submodule_or_a_deletion_is_refused(
    world: World, change: tuple[str, tuple[str, bytes | str] | None], says: str
) -> None:
    path, entry = change
    if entry and entry[0] == "160000":
        entry = ("160000", world.base.encode())
    world.made({path: entry}, document=trial(written=[path]))  # type: ignore[dict-item]
    with pytest.raises(upgrade.RefusedError, match=says):
        world.check()


def test_a_path_the_trial_does_not_name_is_refused(world: World) -> None:
    world.made({"app.py": ("100644", b"x = 2\n"), "pkg/setup.py": ("100644", b"y = 2\n")})
    with pytest.raises(upgrade.RefusedError, match=r"'pkg/setup\.py': the trial does not name it"):
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


def test_a_tree_git_itself_refuses_never_reaches_the_checks(world: World) -> None:
    """A tree with an entry called `.git` is a way to write into the checkout's own git directory.
    Fetched into a checkout that lacks the objects, git's own check stops it (git 2.54 does; the
    path rule, tested above, is the second layer for a git that does not)."""
    blob = plumb(world.repo, "hash-object", "-w", "--stdin", data=b"x\n")
    listing = plumb(world.repo, "ls-tree", world.base) + f"\n100644 blob {blob}\t.git"
    tree = plumb(world.repo, "mktree", data=(listing + "\n").encode())
    made = plumb(
        world.repo, "commit-tree", tree, "-p", world.base, "-m", message(), env=who(*IDENTITY)
    )
    plumb(world.repo, "update-ref", "refs/heads/obelize/upgrade-pydantic-2.12.5", made)
    world.bundle("refs/heads/obelize/upgrade-pydantic-2.12.5")
    world.write(trial(written=[".git"]))
    with pytest.raises(upgrade.RefusedError, match="git fetch failed"):
        world.check()
    assert plumb(world.checkout, "for-each-ref", "refs/obelize-verify/") == ""


@pytest.mark.parametrize("damage", ["truncated", "flipped", "empty pack"])
def test_a_bundle_whose_pack_is_damaged_is_refused(world: World, damage: str) -> None:
    world.made()
    path = world.folder / "upgrade.bundle"
    data = path.read_bytes()
    header, sep, pack = data.partition(b"\n\n")
    if damage == "truncated":
        path.write_bytes(data[:-30])
    elif damage == "flipped":
        middle = len(pack) // 2
        path.write_bytes(
            header + sep + pack[:middle] + bytes([pack[middle] ^ 0xFF]) + pack[middle + 1 :]
        )
    else:
        path.write_bytes(header + sep)
    with pytest.raises(upgrade.RefusedError, match="git "):
        world.check()


def test_a_bundle_with_a_second_branch_or_a_tag_is_refused(world: World) -> None:
    world.made()
    craft(world.repo, "obelize/upgrade-other-1.0", {"app.py": ("100644", b"x = 3\n")})
    world.bundle(
        "refs/heads/obelize/upgrade-pydantic-2.12.5", "refs/heads/obelize/upgrade-other-1.0"
    )
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
    craft(
        world.repo,
        "obelize/upgrade-pydantic-2.12.5",
        {"app.py": ("100644", b"x = 2\n")},
        parent=older,
    )
    world.bundle("refs/heads/obelize/upgrade-pydantic-2.12.5", base="")
    world.write()
    with pytest.raises(upgrade.RefusedError, match="one commit on the commit the job ran on"):
        world.check()


def test_a_bundle_that_needs_a_commit_the_checkout_lacks_is_refused(
    world: World, tmp_path: Path
) -> None:
    other = committed(tmp_path / "other", {"app.py": "x = 9\n"})
    branch = "obelize/upgrade-pydantic-2.12.5"
    craft(other, branch, {"app.py": ("100644", b"x = 2\n")})
    target = str(world.folder / "upgrade.bundle")
    plumb(other, "bundle", "create", target, f"refs/heads/{branch}", f"^{branch}~1")
    world.write()
    with pytest.raises(upgrade.RefusedError, match="git bundle"):
        world.check()


def test_two_commits_are_not_one_commit_on_the_base(world: World) -> None:
    branch = "obelize/upgrade-pydantic-2.12.5"
    first = craft(world.repo, branch, {"app.py": ("100644", b"x = 2\n")})
    craft(world.repo, branch, {"app.py": ("100644", b"x = 3\n")}, parent=first)
    world.bundle(f"refs/heads/{branch}")
    world.write()
    with pytest.raises(upgrade.RefusedError, match="one commit on the commit the job ran on"):
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
    odd = world.artifacts / name
    world.folder.rename(odd)
    with pytest.raises(upgrade.RefusedError, match="is not a folder this action makes"):
        upgrade.verified(odd, world.checkout, world.base)


# The dependencies a workflow asks for.


def test_the_dependencies_asked_for_are_names_and_each_has_a_folder() -> None:
    assert upgrade.named("pydantic  Django_Rest") == (
        ["pydantic", "Django_Rest"],
        ["pydantic", "django-rest"],
    )


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("", "distributions takes the dependencies"),
        ("  ", "distributions takes the dependencies"),
        (" ".join(f"d{n}" for n in range(21)), "distributions takes the dependencies"),
        ("--pack", "distributions takes distribution names"),
        ("a;b", "distributions takes distribution names"),
        ("pydantic Pydantic", "names one dependency twice"),
        ("a_b a.b", "names one dependency twice"),
    ],
)
def test_a_list_that_is_no_list_of_dependencies_is_refused(text: str, says: str) -> None:
    with pytest.raises(upgrade.RefusedError, match=says):
        upgrade.named(text)


# The job that may write: pushing and the pull request.

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
    """A bare repository as `origin` of the checkout, and a `gh` that records what it was asked."""

    def __init__(self, world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.world = world
        self.bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.bare)], check=True)
        plumb(world.repo, "remote", "add", "origin", str(self.bare))
        plumb(world.repo, "push", "-q", "origin", "HEAD:refs/heads/work")
        plumb(world.checkout, "remote", "set-url", "origin", str(self.bare))
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

    def publish(self, branch: str = "main", names: tuple[str, ...] = ("pydantic",)) -> int:
        code: int = upgrade.publish(
            self.world.artifacts, self.world.checkout, self.world.base, branch, list(names)
        )
        return code


@pytest.fixture
def remote(world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Remote:
    return Remote(world, tmp_path, monkeypatch)


@NEEDS_SH
def test_a_verified_branch_is_pushed_as_a_commit_made_here_and_a_pull_request_is_opened(
    remote: Remote, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    tip = world.made()
    assert remote.publish("work") == 0
    assert remote.branches() == ["obelize/upgrade-pydantic-2.12.5", "work"]
    branch = "obelize/upgrade-pydantic-2.12.5"
    on_remote = plumb(remote.bare, "rev-parse", branch)
    assert on_remote != tip
    assert plumb(remote.bare, "rev-parse", f"{branch}^") == world.base
    assert plumb(remote.bare, "rev-parse", f"{branch}^{{tree}}") == plumb(
        world.repo, "rev-parse", f"{tip}^{{tree}}"
    )
    args = Path(f"{remote.record}.args").read_text().splitlines()
    assert args[:8] == ["pr", "create", "--head", branch, "--base", "work", "--title", TITLE]
    assert args[8] == "--body-file"
    assert "opened a pull request" in capsys.readouterr().out
    assert plumb(world.checkout, "for-each-ref", "refs/obelize-verify/") == ""
    body = Path(f"{remote.record}.body").read_text()
    assert body.endswith(upgrade.CLOSING.format(world.base[:10]))
    assert "no test was run or checked by the job that pushed this" in body


@NEEDS_SH
def test_a_folder_the_workflow_did_not_ask_for_is_refused_whatever_it_holds(
    remote: Remote, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.made()
    for number in range(5):
        world.made(name=f"zz{number}")
    assert remote.publish() == 1
    out = capsys.readouterr().out
    assert out.count("not a dependency this workflow asked for") == 5
    assert remote.branches() == ["obelize/upgrade-pydantic-2.12.5", "work"]
    assert remote.calls() == 1


@NEEDS_SH
def test_an_artifact_with_more_folders_than_can_be_asked_for_is_refused_whole(
    remote: Remote, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.made()
    for number in range(upgrade.MAX_DISTRIBUTIONS):
        world.of(f"zz{number}")
    assert remote.publish() == 2
    assert f"the artifact holds {upgrade.MAX_DISTRIBUTIONS + 1} folders" in capsys.readouterr().out
    assert remote.branches() == ["work"]
    assert remote.calls() == 0


@NEEDS_SH
def test_a_dependency_asked_for_that_made_no_folder_is_nothing_to_publish(
    remote: Remote, world: World
) -> None:
    world.made()
    assert remote.publish(names=("pydantic", "attrs")) == 0
    assert remote.calls() == 1


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
    bad = world.of("attrs")
    (bad / "trial.json").write_text("{}", encoding="utf-8")
    assert remote.publish(names=("pydantic", "attrs")) == 1
    assert "::error::attrs: the trial says 'None'" in capsys.readouterr().out
    assert remote.branches() == ["obelize/upgrade-pydantic-2.12.5", "work"]
    assert remote.calls() == 1


@NEEDS_SH
def test_a_refused_folder_pushes_nothing(remote: Remote, world: World) -> None:
    flow = ".github/workflows/ci.yml"
    world.made({flow: ("100644", b"on: push\n")}, document=trial(written=[flow]))
    assert remote.publish() == 1
    assert remote.branches() == ["work"]
    assert remote.calls() == 0
    assert plumb(world.checkout, "for-each-ref", "refs/obelize-verify/") == ""


@NEEDS_SH
@NOT_ON_WINDOWS
def test_a_path_utf_8_cannot_hold_is_refused_and_the_next_folder_is_still_published(
    remote: Remote, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    odd = "a\udcffb.py"
    world.made(
        {odd: ("100644", b"x = 2\n")}, name="aa", document=trial(distribution="aa", written=[odd])
    )
    world.made()
    assert remote.publish(names=("aa", "pydantic")) == 1
    assert "aa: " in capsys.readouterr().out
    assert remote.branches() == ["obelize/upgrade-pydantic-2.12.5", "work"]
    assert remote.calls() == 1


@NEEDS_SH
def test_a_pull_request_text_that_cannot_be_written_is_found_before_anything_is_pushed(
    remote: Remote,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    world.made(name="aa", document=trial(distribution="aa"))
    world.made()
    real = upgrade.verified

    def spoiled(folder: Path, repo: Path, base: str) -> Any:
        result = real(folder, repo, base)
        return result._replace(body="x\udcff") if folder.name == "aa" else result

    monkeypatch.setattr(upgrade, "verified", spoiled)
    assert remote.publish(names=("aa", "pydantic")) == 1
    assert "aa: UnicodeEncodeError" in capsys.readouterr().out
    assert remote.branches() == ["obelize/upgrade-pydantic-2.12.5", "work"]
    assert remote.calls() == 1


@NEEDS_SH
def test_a_crash_in_one_folder_is_said_without_what_it_holds_and_the_next_goes_on(
    remote: Remote,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    world.made(name="aa", document=trial(distribution="aa"))
    world.made()
    real = upgrade.verified

    def crashing(folder: Path, repo: Path, base: str) -> Any:
        if folder.name == "aa":
            raise RuntimeError("secret detail")
        return real(folder, repo, base)

    monkeypatch.setattr(upgrade, "verified", crashing)
    assert remote.publish(names=("aa", "pydantic")) == 1
    out = capsys.readouterr().out
    assert "aa: RuntimeError; nothing more was done" in out
    assert "secret detail" not in out
    assert remote.calls() == 1


@NEEDS_SH
def test_what_the_artifact_names_cannot_end_a_workflow_command_in_the_log(
    remote: Remote, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    odd = "a\n::notice::injected.md"
    world.made({odd: ("100644", b"x\n")}, document=trial(written=[odd]))
    world.of("x\n::notice::injected")
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
    assert (
        "gh pr create exited 1; obelize/upgrade-pydantic-2.12.5 is pushed"
        in capsys.readouterr().out
    )
    assert "obelize/upgrade-pydantic-2.12.5" in remote.branches()


def test_an_artifact_with_no_folder_is_nothing_to_do(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert upgrade.publish(empty, world.checkout, world.base, "main", ["pydantic"]) == 0
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
    assert upgrade.publish(world.artifacts, world.checkout, base, branch, ["pydantic"]) == 2
    assert says in capsys.readouterr().out


@NEEDS_SH
def test_a_symbolic_link_for_a_folder_is_not_one(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    aside = tmp_path / "aside"
    aside.mkdir()
    world.folder.rmdir()
    (world.artifacts / "linked").symlink_to(aside)
    assert upgrade.publish(world.artifacts, world.checkout, world.base, "main", ["pydantic"]) == 0
    assert "the artifact holds no upgrade" in capsys.readouterr().out


# The job that runs the tests.

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
        for name in (*upgrade.TOKENS, "GITHUB_EVENT_NAME", "NO_BRANCH", "TWO_BRANCHES"):
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
        text = self.output.read_text(encoding="utf-8").splitlines() if self.output.exists() else []
        return dict(line.split("=", 1) for line in text)

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
@pytest.mark.parametrize("code", [1, 2, 3, 5, 6])
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
@pytest.mark.parametrize(
    ("codes", "worst"),
    [
        ("alpha=3 beta=1", "1"),
        ("alpha=1 beta=3", "1"),
        ("alpha=3 beta=5", "5"),
        ("alpha=6 beta=2", "2"),
        ("alpha=2 beta=6", "2"),
        ("alpha=3 beta=6", "3"),
        ("alpha=6 beta=3", "6"),
        ("alpha=1 beta=2", "1"),
        ("alpha=0 beta=0", "0"),
    ],
)
def test_a_failure_in_any_dependency_reaches_the_gate_whichever_comes_first(
    job: Job, monkeypatch: pytest.MonkeyPatch, codes: str, worst: str
) -> None:
    """The code is the first that failed outright, else the first that was not proven, else 0."""
    monkeypatch.setenv("CODES", codes)
    assert job.run(OBELIZE_DISTRIBUTIONS="alpha beta") == 0
    assert job.outputs()["exit-code"] == worst
    verdict = upgrade.gate({"OBELIZE_EXIT_CODE": worst, "OBELIZE_FAIL_ON_UNPROVEN": "false"})
    assert (verdict == 0) == (worst in {"0", "3", "6"})


@NEEDS_SH
def test_a_dependency_that_made_a_branch_beside_one_that_failed_is_still_published(
    job: Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODES", "pydantic=6 attrs=0")
    assert job.run(OBELIZE_DISTRIBUTIONS="pydantic attrs") == 0
    outputs = job.outputs()
    assert (outputs["exit-code"], outputs["changed"]) == ("6", "true")
    assert [path.name for path in job.out.iterdir()] == ["attrs"]


@NEEDS_SH
def test_an_upgrade_that_exits_zero_and_makes_no_branch_had_nothing_to_move(
    job: Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_BRANCH", "1")
    assert job.run() == 0
    assert (job.outputs()["exit-code"], job.outputs()["changed"]) == ("0", "false")
    assert not job.out.exists()
    assert "| `pydantic` | 0 | none |" in job.summary.read_text()


@NEEDS_SH
def test_an_upgrade_that_leaves_two_branches_is_not_published(
    job: Job, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TWO_BRANCHES", "1")
    assert job.run() == 0
    assert (job.outputs()["exit-code"], job.outputs()["changed"]) == ("1", "false")


BAD = [
    ({"GITHUB_EVENT_NAME": "pull_request_target"}, "never on pull_request_target"),
    ({"GITHUB_EVENT_NAME": "workflow_run"}, "never on workflow_run"),
    ({"GITHUB_EVENT_NAME": "issue_comment"}, "never on issue_comment"),
    ({"GH_TOKEN": "x"}, "GH_TOKEN is set"),
    ({"GITHUB_TOKEN": "x"}, "GITHUB_TOKEN is set"),
    ({"ACTIONS_ID_TOKEN_REQUEST_TOKEN": "x"}, "ACTIONS_ID_TOKEN_REQUEST_TOKEN is set"),
    ({"OBELIZE_VERSION": ""}, "version takes a release"),
    ({"OBELIZE_VERSION": "latest"}, "version takes a release"),
    ({"OBELIZE_VERSION": "0.9.0 --index-url=https://x"}, "version takes a release"),
    ({"OBELIZE_DISTRIBUTIONS": ""}, "distributions takes the dependencies"),
    ({"OBELIZE_DISTRIBUTIONS": "--pack"}, "distributions takes distribution names"),
    ({"OBELIZE_DISTRIBUTIONS": "$(id)"}, "distributions takes distribution names"),
    ({"OBELIZE_DISTRIBUTIONS": "pydantic Pydantic"}, "names one dependency twice"),
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
@pytest.mark.parametrize(
    ("key", "value", "shown"),
    [
        (
            "http.https://github.com/.extraheader",
            "AUTHORIZATION: basic c2VjcmV0LXZhbHVl",
            "extraheader",
        ),
        (
            "includeIf.gitdir:/home/runner/work/r/r/.git.path",
            "credentials-secret-value",
            "includeif",
        ),
        ("credential.helper", "store --file=secret-value", "credential.helper"),
    ],
)
def test_a_checkout_that_kept_a_credential_stops_the_job_without_saying_what_it_holds(
    job: Job, capsys: pytest.CaptureFixture[str], key: str, value: str, shown: str
) -> None:
    subprocess.run(["git", "-C", str(job.repo), "config", "--local", key, value], check=True)
    assert job.run() == 2
    out = capsys.readouterr().out
    assert "the checkout keeps a credential" in out
    assert shown in out.lower()
    assert "secret-value" not in out
    assert "c2VjcmV0" not in out
    assert "persist-credentials: false" in out
    assert not (job.tmp / "record").exists()


@NEEDS_SH
def test_a_checkout_without_a_credential_in_its_configuration_is_let_through(job: Job) -> None:
    subprocess.run(["git", "-C", str(job.repo), "config", "--local", "user.name", "x"], check=True)
    subprocess.run(
        ["git", "-C", str(job.repo), "config", "--local", "core.autocrlf", "false"], check=True
    )
    assert job.run() == 0
    assert job.outputs()["changed"] == "true"


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


def test_a_report_names_the_files_the_trial_left_as_they_were(tmp_path: Path) -> None:
    document = trial(held=["a.py", "b.py"])
    (tmp_path / "trial.json").write_text(json.dumps(document), encoding="utf-8")
    assert "Left as they were, so the move is partial: `a.py`, `b.py`" in upgrade.report(
        tmp_path, "msg\n"
    )
    document["held"] = []
    (tmp_path / "trial.json").write_text(json.dumps(document), encoding="utf-8")
    assert "Left as they were" not in upgrade.report(tmp_path, "msg\n")


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
        ("6", "false", 0),
        ("3", "true", 3),
        ("6", "true", 6),
        ("4", "false", 4),
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


def _exits(function: str) -> set[int]:
    """The integer codes `typer.Exit` is given in one function of the CLI."""
    tree = ast.parse((ROOT / "src" / "obelize" / "cli.py").read_text(encoding="utf-8"))
    (node,) = [
        one for one in ast.walk(tree) if isinstance(one, ast.FunctionDef) and one.name == function
    ]
    return {
        call.args[0].value
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and ast.unparse(call.func) == "typer.Exit"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, int)
    }


def test_the_codes_that_pass_unless_asked_are_those_a_trial_ending_on_a_branch_gives() -> None:
    """`upgrade --apply --branch` ends in `_trial` and `_commit_branch` and never reaches `fix`'s
    own exits, which is where a `4` comes from."""
    reached = _exits("_trial") | _exits("_commit_branch")
    assert sorted(upgrade.UNPROVEN) == [3, 6]
    assert reached.issuperset(upgrade.UNPROVEN)
    assert 4 not in reached
    text = (ROOT / "docs" / "CLI.md").read_text(encoding="utf-8")
    for code in upgrade.UNPROVEN:
        assert f"| `{code}` |" in text


# The command line.


def test_the_script_takes_a_command_and_each_command_is_run(world: World, tmp_path: Path) -> None:
    script = str(ROOT / "action" / "upgrade.py")
    env = {**os.environ, "OBELIZE_EXIT_CODE": "0", "OBELIZE_FAIL_ON_UNPROVEN": "false"}
    assert subprocess.run([sys.executable, script, "gate"], env=env, check=False).returncode == 0
    empty = tmp_path / "none"
    empty.mkdir()
    publish = [script, "publish", "--artifacts", str(empty), "--repo", str(world.checkout)]
    publish += ["--base", world.base, "--base-branch", "main"]
    given = subprocess.run([sys.executable, *publish], capture_output=True, check=False)
    assert given.returncode == 2
    assert b"--distributions" in given.stderr
    done = subprocess.run([sys.executable, *publish, "--distributions", "pydantic"], check=False)
    assert done.returncode == 0
    odd = subprocess.run(
        [sys.executable, *publish, "--distributions", "--force"], capture_output=True, check=False
    )
    assert odd.returncode == 2
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


def test_lines_end_at_a_line_feed_and_not_at_a_form_feed_or_a_separator() -> None:
    assert upgrade.lines("a\x0cb\nc\u2028d\r\n\ne\x85f\n") == ["a\x0cb", "c\u2028d", "e\x85f"]
