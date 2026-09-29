"""What git says about a repository: `tree` gates `--apply`, and `state` records it in `run.json`.

git failing beside a `.git` is `UnansweredError`, never clean. Untracked files are not dirt, since
obelize writes `.obelize/runs/` itself, unless the plan would rewrite one: git holds no copy of it.
"""

from __future__ import annotations

import subprocess
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from obelize.native import processes

# Seconds; a hung network filesystem must not hold a scan open.
TIMEOUT_S = 30


class UnansweredError(Exception):
    """git is here and did not say where this directory is or what is in it."""


@dataclass(frozen=True, slots=True)
class State:
    """What `run.json` records; `sha`/`branch` only at the top, `dirty` `None` if git cannot say."""

    sha: str | None = None
    branch: str | None = None
    dirty: bool | None = False


@dataclass(frozen=True, slots=True)
class Tree:
    """The work tree a directory is in, as git describes it."""

    toplevel: bool
    # Tracked paths with uncommitted changes anywhere in the repository, spelled from its top.
    modified: tuple[str, ...]
    # Planned paths git does not track, spelled the same way, in the plan's order.
    untracked: tuple[str, ...] = ()


def run(root: Path, *arguments: str) -> str | None:
    """One git command in `root`, or `None`; `surrogateescape` keeps non-UTF-8 paths intact."""
    try:
        completed = subprocess.run(
            [processes.git(), "-C", str(root), *arguments],
            capture_output=True,
            check=False,
            timeout=TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None  # not installed, not executable, or hung
    if completed.returncode != 0:
        return None  # not a repository, or git refused this one
    return completed.stdout.decode("utf-8", "surrogateescape")


def is_toplevel(root: Path) -> bool:
    top = run(root, "rev-parse", "--show-toplevel")
    return top is not None and Path(top.rstrip("\n")).resolve() == root.resolve()


def tree(root: Path, planned: Collection[str] = ()) -> Tree | None:
    """The work tree `root` is in, or `None` when it is in no repository.

    `-z` because porcelain v1 quotes non-ASCII paths; `--show-prefix` because comparing paths
    fails on case-insensitive filesystems. Both names of a rename are reported. `planned` paths
    are relative to `root`.
    """
    prefix = run(root, "rev-parse", "--show-prefix")
    if prefix is None:
        here = root.absolute()
        if not any((directory / ".git").exists() for directory in (here, *here.parents)):
            return None
        raise UnansweredError
    status = run(root, "status", "--porcelain", "--untracked-files=no", "-z")
    if status is None:
        raise UnansweredError
    top = prefix.strip("\n")
    return Tree(
        toplevel=top == "",
        modified=tuple(sorted(_paths(status))),
        untracked=_untracked(root, top, planned),
    )


def _untracked(root: Path, prefix: str, planned: Collection[str]) -> tuple[str, ...]:
    """The planned paths missing from the index; with no plan (`state`, every scan), no listing."""
    if not planned:
        return ()
    listed = run(root, "ls-files", "-z", "--cached")
    if listed is None:
        raise UnansweredError
    tracked = set(listed.split("\0"))
    return tuple(prefix + path for path in planned if path not in tracked)


def _paths(status: str) -> Iterator[str]:
    """The path fields of `--porcelain -z`, including a rename's origin.

    `XY path`: X is the index, Y the work tree; reading only one calls a staged change clean.
    """
    records = iter(status.split("\0")[:-1])
    for record in records:
        yield record[3:]
        if "R" in record[:2] or "C" in record[:2]:
            # The origin is its own record with no status field; consume it here, not in the loop.
            yield from islice(records, 1)


def state(root: Path) -> State:
    """What `run.json` records about the tree at the start of a run."""
    try:
        found = tree(root)
    except UnansweredError:
        return State(dirty=None)
    if found is None:
        return State()
    if not found.toplevel:
        return State(dirty=bool(found.modified))
    head = run(root, "rev-parse", "HEAD")
    branch = run(root, "symbolic-ref", "--short", "-q", "HEAD")
    return State(
        sha=head.strip() if head else None,
        branch=branch.strip() if branch else None,
        dirty=bool(found.modified),
    )


__all__ = ["TIMEOUT_S", "State", "Tree", "UnansweredError", "is_toplevel", "run", "state", "tree"]
