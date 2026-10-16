"""What the suites share: git in a directory, written trees and what a directory holds.

Imported as `support`, like `platforms`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    """`git -C root`, failing loudly; signing is off, or a signing developer's run stops at a key
    prompt."""
    return subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *arguments],
        check=True,
        capture_output=True,
    )
