"""Run a whole scan: the process pool, the repository-wide passes, and the order of the answer.

Output is byte-identical across `--jobs`, `PYTHONHASHSEED` and walk order: libcst yields references
in an identity-ordered set, so every pass sorts by source position and files sort by `sort_key`.
"""

from __future__ import annotations

import multiprocessing
import os
from collections import Counter
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from obelize import fsutil
from obelize.config import ConfigError
from obelize.impact import planner
from obelize.models import (
    DEFAULT_INCLUDE,
    Binding,
    Config,
    Finding,
    ImpactPlan,
    ImpactPolicy,
    ManifestPlan,
    ScanCounts,
    ScanSpec,
)
from obelize.native import processes
from obelize.scan import analysis, manifests, parse, reach, runtime, walker

# Candidates (prefilter survivors, not selected files) before the default starts processes: the
# first size where the pool won with a core to spare. A typed `--jobs` ignores it.
POOL_THRESHOLD: Final = 32

# Default cap: eight cores peaked near 5x, and each worker is an interpreter.
MAX_WORKERS: Final = 8

# Cores left to the parent, which reads, hashes, prefilters, pickles and re-validates. Without
# one, a two-core runner's pool reached parity only at 128 candidates; with one, at 24.
RESERVED_CORES: Final = 1

# On every platform: `fork` is unsafe with threads, and mixed start methods differ in what a
# child inherits.
START_METHOD: Final = "spawn"

# Set once per worker process by `_initialise` rather than pickled with every task.
_WORKER: _Worker | None = None


@dataclass(frozen=True, slots=True)
class _Worker:
    """The two immutable arguments every task in a pool shares."""

    spec: ScanSpec
    policy: ImpactPolicy


@dataclass(frozen=True, slots=True)
class Candidate:
    """A file worth parsing, hashed over the bytes handed on; a worker re-read could differ."""

    path: str
    sha256: str
    data: bytes


@dataclass(frozen=True, slots=True)
class FileResult:
    """One selected file's result; `sha256` is empty exactly when it was refused unread."""

    path: str
    sha256: str
    parsed: bool
    plan: ImpactPlan
    limitations: tuple[parse.Limitation, ...] = ()
    # Kept because `escape_lines` is the evidence for a group's bail and `Binding` lacks it.
    receivers: tuple[analysis.Receiver, ...] = ()


@dataclass(frozen=True, slots=True)
class Scan:
    """One repository, scanned. Nothing here is time-derived or absolute."""

    source: walker.ListingSource
    # In `sort_key` order.
    results: tuple[FileResult, ...]
    # Source and manifest findings alike, in document order.
    findings: tuple[Finding, ...]
    bindings: tuple[Binding, ...]
    manifests: ManifestPlan
    # Declared Python floor; `blocked` on it is run.json's `runtime_unsupported`: no migration.
    runtime: runtime.Declared | None
    skipped: tuple[walker.Skipped, ...]
    limitations: tuple[parse.Limitation, ...]
    counts: ScanCounts
    # Processes that ran (`1` is in-process). run.json only: findings.json may not vary by machine.
    workers: int
    # Default-`include` misses that name the distribution, and imports of legacy-only modules.
    # No plan carries either, so the manifest pin check is asked again after a run.
    unanalysed: tuple[str, ...] = ()
    transitive: tuple[tuple[str, str], ...] = ()

    @property
    def receivers(self) -> tuple[tuple[str, analysis.Receiver], ...]:
        """Every receiver record, paired with the file it was found in."""
        return tuple(
            (result.path, receiver) for result in self.results for receiver in result.receivers
        )


def worker_count(jobs: int | None) -> int:
    """Processes for `--jobs`, owning its usage error; the default spares `RESERVED_CORES`."""
    if jobs is None:
        return max(1, min(MAX_WORKERS, (os.cpu_count() or 1) - RESERVED_CORES))
    if jobs < 1:
        raise ConfigError(f"--jobs must be at least 1, got {jobs}")
    limit = processes.WORKER_LIMIT
    if limit is not None and jobs > limit:
        raise ConfigError(f"--jobs must be at most {limit} on this system, got {jobs}")
    return jobs


def sort_key(result: FileResult) -> tuple[bytes, str]:
    """Path bytes, then hash: paths repeat across roots, and a stable sort keeps input order."""
    return (os.fsencode(result.path), result.sha256)


def ordered(results: Iterable[FileResult]) -> tuple[FileResult, ...]:
    return tuple(sorted(results, key=sort_key))


def examine(candidate: Candidate, spec: ScanSpec, policy: ImpactPolicy) -> FileResult:
    """A worker's whole job: a pure function of bytes, spec and policy, the cache key."""
    read = parse.gates(candidate.path, candidate.data)
    return _graded(candidate.path, candidate.sha256, read, spec, policy)


def payload(result: FileResult) -> dict[str, Any]:
    """`result` as plain data, all that crosses the pool boundary: a libcst node does not pickle."""
    return {
        "path": result.path,
        "sha256": result.sha256,
        "parsed": result.parsed,
        "plan": result.plan.model_dump(mode="json"),
        "limitations": [asdict(row) for row in result.limitations],
        "receivers": [asdict(row) for row in result.receivers],
    }


def restore(row: dict[str, Any]) -> FileResult:
    """The inverse of `payload`; re-validating the plan refuses a malformed worker result."""
    return FileResult(
        path=str(row["path"]),
        sha256=str(row["sha256"]),
        parsed=bool(row["parsed"]),
        plan=ImpactPlan.model_validate(row["plan"]),
        limitations=tuple(parse.Limitation(**entry) for entry in row["limitations"]),
        receivers=tuple(_receiver(entry) for entry in row["receivers"]),
    )


def scan(
    root: Path,
    config: Config,
    spec: ScanSpec,
    policy: ImpactPolicy | None = None,
    jobs: int | None = None,
) -> Scan:
    """Select, read, resolve, grade, then run the passes that need every file's plan.

    `jobs`: `1` is in-process, a typed number is taken as typed, and only the default (`None`)
    stays in-process below `POOL_THRESHOLD`.
    """
    policy = policy or ImpactPolicy()
    selection = walker.walk(root, config)
    candidates, results, transitive = _sift(root, selection.files, spec, config, policy)

    workers = worker_count(jobs)
    if workers == 1 or (jobs is None and len(candidates) < POOL_THRESHOLD):
        workers = 1
        results.extend(examine(candidate, spec, policy) for candidate in candidates)
    else:
        results.extend(_pooled(candidates, spec, policy, workers))
    # After every plan, before the manifest pass: does another module reach a model a rewrite
    # would delete?
    files = reach.revised(root, selection.files, ordered(results), policy)

    # Deliberately unsorted: `manifests.plan` sorts its own rows, and a test pins that.
    readings = [manifests.read(root, name, config) for name in selection.manifests]
    hits, refused = manifests.prefiltered(root, selection.excluded, spec, config)
    # Un-included files block the removal only under the default `include`, which silently skips
    # notebooks; under a narrower one they are the user's choice and reported as excluded.
    unread, unreadable = manifests.prefiltered(root, selection.unincluded, spec, config)
    unanalysed = unread if config.include == DEFAULT_INCLUDE else ()
    hits = tuple(sorted({*hits, *unread})) if not unanalysed else hits
    declared = tuple(row for reading in readings for row in reading.declarations)
    migration = manifests.survey([result.plan for result in files], hits, unanalysed, transitive)
    declarations = manifests.plan(declared, migration, spec)
    floor = runtime.detect(root, selection.manifests, config)

    findings = tuple(
        sorted(
            [row for result in files for row in result.plan.findings] + list(declarations.findings),
            key=lambda finding: finding.sort_key,
        )
    )
    limitations = [row for result in files for row in result.limitations]
    limitations.extend(row for reading in readings for row in reading.limitations)
    limitations.extend(refused)
    limitations.extend(unreadable)
    limitations.extend(floor.limitations)
    return Scan(
        source=selection.source,
        results=files,
        findings=findings,
        bindings=tuple(row for result in files for row in result.plan.bindings),
        manifests=declarations,
        runtime=floor.declared,
        skipped=selection.skipped,
        limitations=_limitations(limitations),
        counts=_counts(len(selection.files), files, findings),
        workers=workers,
        unanalysed=unanalysed,
        transitive=migration.transitive,
    )


def _sift(
    root: Path, files: Sequence[str], spec: ScanSpec, config: Config, policy: ImpactPolicy
) -> tuple[list[Candidate], list[FileResult], list[tuple[str, str]]]:
    """Read every file; finish the unreadable and prefilter-eliminated, return the rest to parse.

    Legacy-only imports are collected here, since a non-candidate's bytes are not kept.
    """
    candidates: list[Candidate] = []
    finished: list[FileResult] = []
    transitive: list[tuple[str, str]] = []
    for path in files:
        data, refused = parse.contents(root, path, config)
        if data is None:
            read = parse.Read(path=path, status="not_read", limitations=refused)
            finished.append(_graded(path, "", read, spec, policy))
            continue
        transitive.extend(manifests.provided(path, data, spec))
        digest = fsutil.sha256(data)
        if not parse.candidate(data, spec.prefilter_tokens):
            read = parse.Read(path=path, status="not_a_candidate", data=data)
            finished.append(_graded(path, digest, read, spec, policy))
            continue
        candidates.append(Candidate(path=path, sha256=digest, data=data))
    return candidates, finished, transitive


def _pooled(
    candidates: Sequence[Candidate], spec: ScanSpec, policy: ImpactPolicy, workers: int
) -> list[FileResult]:
    """Grade candidates in `workers` spawned processes.

    `BrokenProcessPool` propagates on purpose: an in-process fallback would hide an interpreter
    that cannot be re-created (e.g. obelize reached via a `sys.path` shim).
    """
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context(START_METHOD),
        initializer=_initialise,
        initargs=(spec.model_dump_json(), policy.model_dump_json()),
    ) as executor:
        tasks = [(candidate.path, candidate.sha256, candidate.data) for candidate in candidates]
        return [restore(row) for row in executor.map(_work, tasks)]


def _initialise(spec: str, policy: str) -> None:
    global _WORKER
    _WORKER = _Worker(
        spec=ScanSpec.model_validate_json(spec), policy=ImpactPolicy.model_validate_json(policy)
    )


def _work(task: tuple[str, str, bytes]) -> dict[str, Any]:
    """At module level so that `spawn` can pickle it by name."""
    worker = _WORKER
    if worker is None:
        raise RuntimeError("a scan worker ran before its initializer; this is an obelize defect")
    path, digest, data = task
    candidate = Candidate(path=path, sha256=digest, data=data)
    return payload(examine(candidate, worker.spec, worker.policy))


def _graded(
    path: str, digest: str, read: parse.Read, spec: ScanSpec, policy: ImpactPolicy
) -> FileResult:
    """Grade any read, tree or not, so an empty plan is an output rather than a special case."""
    result = analysis.analyse(read, spec)
    return FileResult(
        path=path,
        sha256=digest,
        parsed=read.status == "parsed",
        plan=planner.plan(result, spec, policy),
        limitations=read.limitations,
        receivers=result.receivers,
    )


def _receiver(entry: dict[str, Any]) -> analysis.Receiver:
    """One receiver record, its two lists back to tuples."""
    return analysis.Receiver(
        **{
            **entry,
            "use_lines": tuple(entry["use_lines"]),
            "escape_lines": tuple(entry["escape_lines"]),
        }
    )


def _limitations(rows: Iterable[parse.Limitation]) -> tuple[parse.Limitation, ...]:
    """Sorted, and de-duplicated because `setup.py` is read twice on purpose."""
    return tuple(sorted(set(rows), key=lambda row: (os.fsencode(row.path), row.code, row.detail)))


def _counts(selected: int, files: Sequence[FileResult], findings: Sequence[Finding]) -> ScanCounts:
    """The summary, recomputed from the findings so it cannot disagree with them."""
    split = Counter(finding.scan_status for finding in findings)
    return ScanCounts(
        files_selected=selected,
        files_parsed=sum(1 for result in files if result.parsed),
        findings=len(findings),
        eligible=split["eligible"],
        needs_review=split["needs_review"],
        unsupported=split["unsupported"],
        not_a_usage=split["not_a_usage"],
    )


__all__ = [
    "MAX_WORKERS",
    "POOL_THRESHOLD",
    "START_METHOD",
    "Candidate",
    "FileResult",
    "Scan",
    "examine",
    "ordered",
    "payload",
    "restore",
    "scan",
    "sort_key",
    "worker_count",
]
