"""What the suites share: git in a directory, written trees and what a directory holds.

Imported as `support`, like `platforms`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    """`git -C root`, failing loudly; signing is off, or a signing developer's run stops at a key
    prompt."""
    return subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *arguments],
        check=True,
        capture_output=True,
    )


def write_tree(root: Path, files: Mapping[str, str | bytes]) -> Path:
    """`files` under `root`, directories made; text goes down as UTF-8, its newlines untouched."""
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body if isinstance(body, bytes) else body.encode())
    return root


def init_repo(root: Path) -> None:
    """A git repository at `root`, on `work`, whose commits are by a fixed name."""
    git(root, "init", "-q", "-b", "work")
    git(root, "config", "user.name", "obelize tests")
    git(root, "config", "user.email", "tests@obelize.invalid")


def commit_all(root: Path, message: str = "before") -> None:
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)


def committed(root: Path, files: Mapping[str, str | bytes]) -> Path:
    """A new repository at `root`, `files` its first commit."""
    root.mkdir(parents=True)
    write_tree(root, files)
    init_repo(root)
    commit_all(root)
    return root
