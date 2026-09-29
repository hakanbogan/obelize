"""`obelize undo`: putting back exactly what this run wrote, and nothing else.

A file is reverted only while its sha256 is the one the run wrote (no `--force`), and
only from a snapshot whose bytes hash to its name. Every edit gets a row, skipped ones included.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from obelize import __version__, fsutil
from obelize.commands import CommandError
from obelize.evidence import run_dir
from obelize.models import UndoFile, UndoRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from obelize.evidence.folder import RunFolder
    from obelize.models import ExitCode, FileEdit, UndoSkip


@dataclass(frozen=True, slots=True)
class Request:
    root: Path
    run_id: str
    argv: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Outcome:
    """What came back, and where the account was written."""

    exit_code: ExitCode
    record: UndoRecord
    # Repository-relative.
    folder: str
    evidence: str


def run(request: Request) -> Outcome:
    """Revert one applied run, file by file, and write `undo.json`."""
    try:
        loaded = run_dir.load(request.root, request.run_id)
    except run_dir.EvidenceError as error:
        # An apply interrupted between its journal and `run.json`: copies and rows exist.
        stopped = run_dir.interrupted(request.root, request.run_id)
        if stopped is None:
            raise CommandError(str(error), 2) from error
        rows, folder, relative = stopped.file_edits, stopped.folder, stopped.relative
    else:
        record = loaded.record
        if record.mode != "apply":
            raise CommandError(
                f"{record.run_id} is a {record.mode!r} run: it wrote no file, so there is "
                f"nothing to put back.",
                2,
            )
        rows, folder, relative = record.file_edits, loaded.folder, loaded.relative

    files = tuple(_one(request.root, folder, row) for row in rows)
    reverted = [row for row in files if row.outcome == "reverted"]
    code: ExitCode = 0 if files and len(reverted) == len(files) else 4
    undo = UndoRecord(
        run_id=request.run_id,
        obelize_version=__version__,
        exit_code=code,
        argv=request.argv,
        undone_at=run_dir.instant(run_dir.now()),
        files=files,
    )
    try:
        evidence = run_dir.undone(folder, relative, undo)
    except run_dir.EvidenceError as error:
        raise CommandError(str(error), 1) from error
    return Outcome(exit_code=code, record=undo, folder=relative, evidence=evidence)


def _one(root: Path, folder: RunFolder, row: FileEdit) -> UndoFile:
    """One recorded edit, put back or skipped; the check order makes each skip reason specific."""
    stored = run_dir.snapshot(row.before_sha256)
    if fsutil.unusable(row.path):
        # Before any read by path: Windows opens `aux.py` as a device and `C:x` elsewhere.
        return _skipped(row, stored, "outside_root", None)
    current = _digest(root / row.path)
    if current is None:
        return _skipped(row, stored, _unreadable(root, row.path), None)
    if current != row.after_sha256:
        return _skipped(row, stored, "hash_mismatch", current)
    original = _original(folder, stored, row.before_sha256)
    if original is None:
        return _skipped(row, stored, "snapshot_unusable", current)
    refusal = fsutil.write(root, row.path, original)
    if refusal is not None:
        return _skipped(row, stored, refusal, current)
    return UndoFile(
        path=row.path,
        outcome="reverted",
        recorded_sha256=row.after_sha256,
        current_sha256=current,
        snapshot=stored,
    )


def _skipped(row: FileEdit, stored: str, reason: UndoSkip, current: str | None) -> UndoFile:
    return UndoFile(
        path=row.path,
        outcome="skipped",
        reason=reason,
        recorded_sha256=row.after_sha256,
        current_sha256=current,
        snapshot=stored,
    )


def _unreadable(root: Path, path: str) -> UndoSkip:
    """Why the file could not be read: the path guard's reason, else `unreadable`."""
    return fsutil.refusal(root, root / path) or "unreadable"


def _original(folder: RunFolder, stored: str, digest: str) -> bytes | None:
    """The snapshot's bytes, or `None` when they do not hash to its name.

    Read through the run folder, not by path, so a symlinked snapshot cannot inject outside bytes.
    """
    try:
        data = folder.read(stored)
    except OSError:
        return None
    return data if fsutil.sha256(data) == digest else None


def _digest(path: Path) -> str | None:
    """The sha256 at this path now, or `None` if nothing readable is there."""
    try:
        return fsutil.sha256(fsutil.read(path))
    except OSError:
        return None


__all__ = ["Outcome", "Request", "run"]
