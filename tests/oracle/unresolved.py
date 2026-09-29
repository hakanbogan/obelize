"""ruff's opinion of whether a Python file binds every name it reads.

`compile()` accepts an unbound name (the `NameError` comes at run time). The oracles ask this of
the bytes a run writes, beside the driver's own gate, and of the hand-written keys.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from pathlib import Path

# Undefined name, unused redefinition, local read before assignment, typing-only import used live.
RULES = "F821,F811,F823,TC004"


def names_unresolved(*paths: Path) -> str:
    """ruff's findings over `paths`, one per line; empty when there are none."""
    checked = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--isolated",
            "--select",
            RULES,
            "--output-format",
            "concise",
            *map(str, paths),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return "" if checked.returncode == 0 else checked.stdout + checked.stderr
