"""The work behind the commands that change or check a repository; `obelize.cli` owns the CLI.

Kept out of cli.py for its startup budget. They return values and never print or `sys.exit`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from obelize.models import ExitCode


class CommandError(Exception):
    """A fatal command error with its exit code (2 usage, 1 unexpected), so no handler guesses."""

    def __init__(self, message: str, code: ExitCode) -> None:
        super().__init__(message)
        self.code = code


def reports(directory: Path) -> dict[str, bytes]:
    """The junit files one verification phase left in `directory`, by bare name, in memory."""
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


__all__ = ["CommandError", "reports"]
