"""A commit on a new branch, made without touching the working tree, the index or a hook.

Git's plumbing builds it: the files go in as objects, a temporary index starts from `HEAD` and takes
them, the tree it writes is committed on top of `HEAD`, and a new ref points at the commit. No
checkout happens, so what is uncommitted stays; no hook runs, since none is a plumbing command's;
nothing is signed, since a signing prompt would hang a command nobody watches. Nothing is pushed.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple

from obelize.native import processes

if TYPE_CHECKING:
    from collections.abc import Mapping

TIMEOUT_S: Final = 60
_PLAIN: Final = "100644"


class BranchError(Exception):
    """A branch that could not be made, with what git said."""


def commit(root: Path, name: str, changes: Mapping[str, bytes], message: str) -> str:
    """Commit `changes` (paths below `root`, with their new bytes) on `HEAD` as the new branch
    `name`, and return the commit."""
    if _asks(root, "check-ref-format", "--branch", name) is None:
        raise BranchError(f"{name!r} is not a name git accepts for a branch")
    head = _asks(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if head is None:
        raise BranchError("the repository has no commit to build on")
    if _asks(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"):
        raise BranchError(f"the branch {name} exists already; obelize never moves one")
    parent = head.strip()
    prefix = _git(root, "rev-parse", "--show-prefix").strip()
    with tempfile.TemporaryDirectory(prefix="obelize-branch-") as folder:
        index = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
        _git(root, "read-tree", parent, env=index)
        for path, data in sorted(changes.items()):
            top = f"{prefix}{path}"
            blob = _git(root, "hash-object", "-w", "--stdin", "--path", top, data=data).strip()
            entry = f"{_mode(root, top)},{blob},{top}"
            _git(root, "update-index", "--add", "--cacheinfo", entry, env=index)
        tree = _git(root, "write-tree", env=index).strip()
        made = _git(root, "commit-tree", tree, "-p", parent, "-m", message).strip()
        _git(root, "update-ref", f"refs/heads/{name}", made, "")
    return made


def _mode(root: Path, top: str) -> str:
    """The mode `HEAD` gives a file, so an executable stays one; a new file is a plain one."""
    listed = _asks(root, "ls-tree", "HEAD", "--", top)
    return listed.split()[0] if listed else _PLAIN


class _Done(NamedTuple):
    ok: bool
    out: str
    err: str


def _run(
    root: Path,
    arguments: tuple[str, ...],
    env: Mapping[str, str] | None,
    data: bytes | None,
) -> _Done:
    """One git command in `root`.

    `core.fsmonitor` is emptied, hooks are looked for nowhere (`update-ref` runs
    `reference-transaction`, and a repository's own configuration says where hooks are) and signing
    is turned off: neither a hook nor a key prompt may run under a command asked to commit.
    """
    try:
        done = subprocess.run(
            [
                processes.git(),
                "-c",
                "core.fsmonitor=",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(root),
                *arguments,
            ],
            input=data,
            capture_output=True,
            check=False,
            timeout=TIMEOUT_S,
            env={**os.environ, **(env or {})},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BranchError(f"git {arguments[0]} did not run: {error}") from error
    return _Done(
        done.returncode == 0,
        done.stdout.decode("utf-8", "surrogateescape"),
        done.stderr.decode("utf-8", "replace").strip(),
    )


def _git(
    root: Path,
    *arguments: str,
    env: Mapping[str, str] | None = None,
    data: bytes | None = None,
) -> str:
    """The output of a git command that must succeed."""
    done = _run(root, arguments, env, data)
    if not done.ok:
        raise BranchError(f"git {arguments[0]} failed: {done.err}")
    return done.out


def _asks(root: Path, *arguments: str) -> str | None:
    """The output of a git command, or `None` if it said no."""
    done = _run(root, arguments, None, None)
    return done.out if done.ok else None


__all__ = ["BranchError", "commit"]
