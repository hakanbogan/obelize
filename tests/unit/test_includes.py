"""`-r` and `-c` includes: a file no name makes a manifest is read when a pip manifest names it.

It is read as a pip-tools input is, for its declarations, and never written: a legacy pin in it is
a row the coupled pack holds the repository for, where it used to be no row at all.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from obelize.cli import app
from obelize.models import Config
from obelize.packs import loader
from obelize.scan import manifests, runner, walker
from platforms import PYTHON, posix_only
from support import commit_all, committed, git, init_repo, write_tree

OPENAI = loader.to_scan_spec(loader.load("openai/openai-0-to-1"))
CALL = "import openai\n\nresponse = openai.ChatCompletion.create(model='m', messages=[])\n"


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        ("requirements.txt", "-r base.pip\n", [("base.pip", "required")]),
        ("requirements.txt", "--requirement base.pip\n", [("base.pip", "required")]),
        ("requirements.txt", "--requirement=base.pip\n", [("base.pip", "required")]),
        ("requirements.txt", "-r  base.pip   # the rest\n", [("base.pip", "required")]),
        ("requirements.txt", "-c pins.pip\n", [("pins.pip", "constrained")]),
        ("requirements.txt", "--constraint pins.pip\n", [("pins.pip", "constrained")]),
        ("requirements.txt", "-r \\\n  base.pip\n", [("base.pip", "required")]),
        ("requirements.txt", "-r ./sub//base.pip\n", [("sub/base.pip", "required")]),
        ("app/requirements.txt", "-r base.pip\n", [("app/base.pip", "required")]),
        ("app/requirements.txt", "-r ../shared/base.pip\n", [("shared/base.pip", "required")]),
        ("app/requirements.txt", "-r ../../base.pip\n", []),
        ("requirements.txt", "-r ../base.pip\n", []),
        ("requirements.txt", "-r sub/../../base.pip\n", []),
        ("requirements.txt", "-r ..\n", []),
        ("requirements.txt", "-r /etc/base.pip\n", []),
        ("requirements.txt", "-r C:\\base.pip\n", []),
        ("requirements.txt", "-r \\\\host\\share\\base.pip\n", []),
        ("requirements.txt", "-r sub\\base.pip\n", [("sub/base.pip", "required")]),
        ("app/requirements.txt", "-r ..\\shared\\base.pip\n", [("shared/base.pip", "required")]),
        ("app/requirements.txt", "-r ..\\..\\base.pip\n", []),
        ("requirements.txt", "-r 'my file.pip'\n", []),
        ("requirements.txt", "-r my file.pip\n", []),
        ("requirements.txt", "-r\n", []),
        ("requirements.txt", "-rbase.pip\n", []),
        ("requirements.txt", "-e ./base.pip\n--index-url https://h/simple\nopenai==0.28.1\n", []),
        ("requirements.txt", "# -r base.pip\n", []),
    ],
)
def test_an_include_is_a_file_of_the_repository_resolved_where_pip_resolves_it(
    path: str, text: str, expected: list[tuple[str, str]]
) -> None:
    assert list(manifests.includes(path, text.encode())) == expected


def test_a_constraints_file_declares_nothing() -> None:
    assert manifests.constrains("constraints.txt") is True
    assert manifests.constrains("deploy/requirements-constraints.txt") is True
    assert manifests.constrains("requirements.txt") is False
    assert manifests.constrains("pins.pip") is False
    (found,) = manifests.declarations("constraints.txt", b"openai==0.28.1\n")
    assert found.constraint is True
    (other,) = manifests.declarations("requirements.txt", b"openai==0.28.1\n")
    assert other.constraint is False


def test_a_followed_file_is_read_as_an_input_is_and_a_path_with_no_layout_declares_nothing() -> (
    None
):
    data = b"openai==0.28.1\nflask\nsix>=1\n"
    assert manifests.declarations("base.pip", data) == ()
    required = manifests.declarations("base.pip", data, "required")
    assert [(row.name, row.spec, row.pin, row.constraint) for row in required] == [
        ("openai", "==0.28.1", None, False),
        ("six", ">=1", None, False),
    ]
    constrained = manifests.declarations("base.pip", data, "constrained")
    assert [row.constraint for row in constrained] == [True, True]
    assert manifests.read("base.pip", lambda path: (data, ()), "required").declarations == required


Followed = Callable[..., walker.Walk]


@pytest.fixture
def follow(tmp_path: Path) -> Followed:
    """`walker.follow` over a new repository of `files`, reading from the disk."""

    made = count()

    def make(
        files: Mapping[str, str | bytes],
        config: Config | None = None,
        read: Callable[[str], bytes | None] | None = None,
    ) -> walker.Walk:
        root = write_tree(tmp_path / f"repo{next(made)}", files)
        init_repo(root)
        commit_all(root)
        config = config or Config()

        def disk(path: str) -> bytes | None:
            return (root / path).read_bytes()

        return walker.follow(root, config, walker.walk(root, config), read or disk)

    return make


def test_a_chain_of_includes_is_followed_to_its_end(follow: Followed) -> None:
    found = follow(
        {
            "requirements.txt": "-r a.pip\n",
            "a.pip": "-r sub/b.pip\n",
            "sub/b.pip": "-r ../c.pip\nopenai\n",
            "c.pip": "six\n",
            "d.pip": "six\n",
        }
    )
    assert found.followed == (
        ("a.pip", "required"),
        ("c.pip", "required"),
        ("sub/b.pip", "required"),
    )
    assert found.manifests == ("a.pip", "c.pip", "requirements.txt", "sub/b.pip")
    assert found.skipped == ()


def test_the_walk_itself_follows_nothing(tmp_path: Path) -> None:
    root = write_tree(tmp_path, {"requirements.txt": "-r a.pip\n", "a.pip": "six\n"})
    assert walker.walk(root, Config()).followed == ()


def test_a_cycle_ends_where_it_began(follow: Followed) -> None:
    found = follow(
        {
            "requirements.txt": "-r a.pip\n-r requirements.txt\n",
            "a.pip": "-r b.pip\n-r a.pip\n",
            "b.pip": "-r a.pip\n-r requirements.txt\n",
        }
    )
    assert found.followed == (("a.pip", "required"), ("b.pip", "required"))


def test_a_chain_is_followed_no_deeper_than_the_bound(follow: Followed) -> None:
    length = manifests.MAX_DEPTH + 2
    files = {"requirements.txt": "-r c1.pip\n"}
    files.update({f"c{n}.pip": f"-r c{n + 1}.pip\n" for n in range(1, length)})
    files[f"c{length}.pip"] = "six\n"
    found = follow(files)
    assert [path for path, _ in found.followed] == sorted(
        f"c{n}.pip" for n in range(1, manifests.MAX_DEPTH + 1)
    )


@pytest.mark.parametrize(
    "line",
    ["-r missing.pip", "-r ../outside.pip", "-r /etc/hosts", "-r C:\\Windows\\win.ini", "-r .."],
)
def test_a_file_that_is_missing_or_outside_the_repository_is_never_read(
    follow: Followed, line: str
) -> None:
    reads: list[str] = []

    def read(path: str) -> bytes | None:
        reads.append(path)
        return f"{line}\n".encode()

    found = follow({"requirements.txt": f"{line}\n"}, read=read)
    assert (found.followed, found.skipped) == ((), ())
    assert reads == ["requirements.txt"]


def test_a_windows_separator_is_a_separator_on_every_system(follow: Followed) -> None:
    found = follow(
        {"app/requirements.txt": "-r ..\\shared\\base.pip\n", "shared/base.pip": "openai\n"}
    )
    assert found.followed == (("shared/base.pip", "required"),)


@posix_only("Windows cannot name a file with a backslash")
def test_a_file_named_with_a_backslash_is_not_the_file_it_names(follow: Followed) -> None:
    """The name `a\\b.pip` is refused by the walk, so the include of `a/b.pip` finds nothing."""
    found = follow({"requirements.txt": "-r a\\b.pip\n", "a\\b.pip": "openai\n"})
    assert found.followed == ()


@posix_only("a symbolic link is a POSIX file")
def test_a_link_is_not_followed_and_is_named(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "repo", {"requirements.txt": "-r link.pip\n"})
    outside = write_tree(tmp_path / "out", {"base.pip": "openai\n"}) / "base.pip"
    (root / "link.pip").symlink_to(outside)
    init_repo(root)
    commit_all(root)
    config = Config()
    found = walker.follow(
        root, config, walker.walk(root, config), lambda path: (root / path).read_bytes()
    )
    assert found.followed == ()
    assert [(row.path, row.reason) for row in found.skipped] == [("link.pip", "symlink")]


def test_a_listed_file_that_is_gone_from_the_disk_is_named_once(tmp_path: Path) -> None:
    root = write_tree(
        tmp_path, {"requirements.txt": "-r gone.pip\n-c gone.pip\n-r gone.pip\n", "gone.pip": "x\n"}
    )
    init_repo(root)
    commit_all(root)
    (root / "gone.pip").unlink()
    config = Config()
    found = walker.follow(
        root, config, walker.walk(root, config), lambda path: (root / path).read_bytes()
    )
    assert found.followed == ()
    assert [(row.path, row.reason) for row in found.skipped] == [("gone.pip", "missing")]


def test_what_the_scan_leaves_out_is_not_followed(follow: Followed) -> None:
    files = {
        "requirements.txt": "-r vendor/a.pip\n-r shared/b.pip\n-r c.pip\n",
        "vendor/a.pip": "openai\n",
        "shared/b.pip": "openai\n",
        "c.pip": "six\n",
    }
    found = follow(files, Config(exclude=("shared/**",)))
    assert found.followed == (("c.pip", "required"),)


def test_a_manifest_by_name_is_read_as_it_was_and_not_followed(follow: Followed) -> None:
    found = follow({"requirements.txt": "-r requirements-dev.txt\n", "requirements-dev.txt": "x\n"})
    assert (found.followed, found.manifests) == ((), ("requirements-dev.txt", "requirements.txt"))


def test_only_a_pip_layout_names_includes(follow: Followed) -> None:
    files = {"pyproject.toml": "[project]\n# -r a.pip\n", "setup.cfg": "-r a.pip\n", "a.pip": "x\n"}
    assert follow(files).followed == ()


@pytest.mark.parametrize("lines", ["-c a.pip\n-r a.pip\n", "-r a.pip\n-c a.pip\n"])
def test_a_file_that_one_line_declares_by_is_declared_by(follow: Followed, lines: str) -> None:
    found = follow({"requirements.txt": lines, "a.pip": "-r b.pip\n", "b.pip": "x\n"})
    assert found.followed == (("a.pip", "required"), ("b.pip", "required"))


def test_what_a_constraint_includes_is_a_constraint(follow: Followed) -> None:
    found = follow({"requirements.txt": "-c a.pip\n", "a.pip": "-r b.pip\n", "b.pip": "x\n"})
    assert found.followed == (("a.pip", "constrained"), ("b.pip", "constrained"))
    named = follow({"constraints.txt": "-r b.pip\n", "b.pip": "x\n"})
    assert named.followed == (("b.pip", "constrained"),)


def test_a_manifest_the_reader_cannot_open_names_no_include(follow: Followed) -> None:
    found = follow({"requirements.txt": "-r a.pip\n", "a.pip": "x\n"}, read=lambda path: None)
    assert found.followed == ()


# From a repository to a scan, and to a run.


def scan(root: Path) -> runner.Scan:
    return runner.scan(root, Config(), OPENAI, jobs=1)


def held(found: runner.Scan) -> list[tuple[str, str | None]]:
    return [
        (row.path, row.bail) for row in found.manifests.findings if row.scan_status != "eligible"
    ]


@pytest.mark.parametrize(
    ("flag", "kind"), [("-r", "required"), ("--requirement=", "required"), ("-c", "constrained")]
)
def test_a_legacy_pin_in_a_followed_file_is_a_row_the_coupled_pack_holds_the_repository_for(
    tmp_path: Path, flag: str, kind: str
) -> None:
    files = {
        "app.py": CALL,
        "requirements.txt": f"{flag} base.pip\n",
        "base.pip": "openai==0.28.1\n",
    }
    found = scan(write_tree(tmp_path / "with", files))
    assert found.followed == (("base.pip", kind),)
    assert held(found) == [("base.pip", "manifest_pin_shape_unsupported")]
    without = scan(write_tree(tmp_path / "without", {**files, "requirements.txt": "flask\n"}))
    assert (without.followed, held(without)) == ((), [])


def test_an_include_the_scan_cannot_follow_is_no_row(tmp_path: Path) -> None:
    files = {"app.py": CALL, "requirements.txt": "-r ../base.pip\nopenai==0.28.1\n"}
    found = scan(write_tree(tmp_path, files))
    assert found.followed == ()
    assert [row.path for row in found.manifests.findings] == ["requirements.txt"]


runner_ = CliRunner()
QUIET = f"{PYTHON} -c pass"


def command(tree: Path, *arguments: str) -> Any:
    return runner_.invoke(app, [*arguments, "--repo", str(tree)])


def test_a_run_holds_every_file_for_a_legacy_pin_in_a_followed_file(tmp_path: Path) -> None:
    files = {
        "app.py": CALL,
        "requirements.txt": "flask==3.0\nopenai==0.28.1\n-r extra.pip\n",
        "extra.pip": "openai==0.28.1\n",
    }
    tree = committed(tmp_path / "repo", files)
    result = command(tree, "fix", "--apply", "--allow-dirty", "--verify", QUIET)
    assert result.exit_code == 4, result.output
    assert "manifest_pin_shape_unsupported" in result.output
    for path, text in files.items():
        assert (tree / path).read_text(encoding="utf-8") == text, path


def test_a_run_moves_the_pin_beside_a_followed_file_it_never_writes(tmp_path: Path) -> None:
    files = {
        "app.py": CALL,
        "requirements.txt": "flask==3.0\nopenai==0.28.1\n-r extra.pip\n",
        "extra.pip": "rich\n",
    }
    tree = committed(tmp_path / "repo", files)
    result = command(tree, "fix", "--apply", "--allow-dirty", "--verify", QUIET)
    assert result.exit_code == 0, result.output
    assert (tree / "requirements.txt").read_text(encoding="utf-8") == (
        "flask==3.0\nopenai>=1.109.1\n-r extra.pip\n"
    )
    assert (tree / "extra.pip").read_text(encoding="utf-8") == "rich\n"
    assert git(tree, "status", "--porcelain", "extra.pip").stdout == b""
