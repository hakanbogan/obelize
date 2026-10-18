"""Where a test that the move broke points into code the move changed, as places to put to a model.

Only a traceback frame in a file the move wrote, and not in a test, is a place: a test is the
evidence, so it is never the thing a model edits. The function the frame is in stands for the
symbol the guard wants a proposal to name. The answers go through `resolve`, and so through the
guard.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

from obelize.resolve import Row
from obelize.verify import redact

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path

# A frame of Python's own traceback (`pytest --tb=native`), which is what the trial runs.
_FRAME: Final = re.compile(r'^\s*File "([^"]+)", line (\d+), in (\S+)', re.MULTILINE)
_NOTE_LIMIT: Final = 300


def is_test(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
        or bool({"test", "tests"} & set(parts[:-1]))
    )


def rows(
    work: Path,
    failures: Mapping[str, str],
    changed: Collection[str],
    environ: Mapping[str, str],
) -> list[Row]:
    """For each failing test, its innermost frame in a changed file that is not a test."""
    edits = {name for name in changed if not is_test(name)}
    found: dict[tuple[str, int], Row] = {}
    for test, text in sorted(failures.items()):
        for given, line, function in reversed(_FRAME.findall(text)):
            path = _inside(work, given)
            if path in edits:
                tail = text.strip().splitlines()[-1].strip()[:_NOTE_LIMIT] if text.strip() else ""
                note = redact.redact(
                    f"{test} passed before the move and fails after it: {tail}", environ
                )
                found.setdefault((path, int(line)), Row(path, int(line), function, note))
                break
    return sorted(found.values(), key=lambda row: (row.path, row.line))


def _inside(work: Path, given: str) -> str | None:
    """`given` as a path relative to the copy, or `None` if it is outside it."""
    try:
        return (work / given).resolve().relative_to(work.resolve()).as_posix()
    except ValueError:
        return None
