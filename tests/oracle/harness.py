"""Scan one oracle case with `runner.scan`, the code that ships, and read its answer key back.

`symbol`, `expected` and `scan_status` are the only normalisations of the hand-written keys.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from obelize import config as configuration
from obelize import fsutil
from obelize.models import Binding, Config, Finding, ManifestPlan, ScanSpec
from obelize.packs import loader
from obelize.scan import analysis, runner, walker
from obelize.transforms import codemod

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent / "harness.yaml"
BUNDLED_PACK = "gemini/google-generativeai-to-google-genai"

# Keyed by the names `tests/unit/test_fixture_vocabulary.py` uses.
CASES: dict[str, Path] = {
    directory.name: directory
    for directory in sorted((ROOT / "tests" / "fixtures" / "scan").glob("*/ground_truth.yaml"))
    for directory in [directory.parent]
}
CASES["gemini-legacy-app"] = ROOT / "examples" / "gemini-legacy-app"


@dataclass(frozen=True, slots=True)
class Case:
    """One case's answer key and the scan that was graded against it."""

    name: str
    root: Path
    key: dict[str, Any]
    scan: runner.Scan

    @property
    def findings(self) -> tuple[Finding, ...]:
        return self.scan.findings

    @property
    def bindings(self) -> tuple[Binding, ...]:
        return self.scan.bindings

    @property
    def receivers(self) -> tuple[tuple[str, analysis.Receiver], ...]:
        """Kept because `escape_lines` is graded and a `Binding` does not carry it."""
        return self.scan.receivers

    @property
    def manifests(self) -> ManifestPlan:
        """Kept whole: the files blocking the removal are not findings, so are asserted alone."""
        return self.scan.manifests

    @property
    def graded(self) -> list[dict[str, Any]]:
        return list(self.key["findings"])

    def by_key(self) -> dict[tuple[str, int, str, str, str | None], Finding]:
        return {_produced(finding): finding for finding in self.findings}


def spec() -> ScanSpec:
    return loader.to_scan_spec(loader.load(BUNDLED_PACK))


def document() -> dict[str, dict[str, Any]]:
    loaded = yaml.safe_load(HARNESS.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    unknown = sorted(set(loaded) - set(CASES) - {"all"})
    assert not unknown, f"harness.yaml has sections for no such case: {unknown}"
    return loaded


def exclusions() -> dict[str, tuple[str, ...]]:
    """The per-case corpus exclusions, with `all` folded into every case."""
    sections = document()
    shared = tuple(sections["all"]["exclude"])
    return {name: shared + tuple(sections.get(name, {}).get("exclude", ())) for name in CASES}


def configured(name: str) -> tuple[Path, Config, ScanSpec]:
    """One case's root, config and spec, which the determinism test scans at several `--jobs`."""
    root = CASES[name]
    config = configuration.load(root).config
    extra = exclusions()[name]
    config = config.model_copy(update={"exclude": tuple(sorted(set(config.exclude) | set(extra)))})
    return root, config, spec()


def driven(source: Path, work: Path, pack_id: str = BUNDLED_PACK) -> tuple[Path, dict[str, Any]]:
    """Copy, scan and codemod a repository; return the copy and `providers.base.questions` kwargs.

    The copy keeps run folders out of `tests/fixtures/`, where a later scan would read them.
    """
    shutil.copytree(source, work / "repo")
    root = work / "repo"
    shutil.rmtree(root / ".obelize", ignore_errors=True)
    pack = loader.load(pack_id)
    projection = loader.to_scan_spec(pack)
    config = configuration.load(root).config
    scan = runner.scan(root, config, projection, jobs=1)
    selection = walker.walk(root, config)
    wanted = {result.path for result in scan.results} | set(selection.manifests)
    sources = {name: fsutil.read(root / name) for name in sorted(wanted)}
    run = codemod.run(scan, sources, pack.pack, projection)
    return root, {
        "findings": run.findings,
        "plans": run.plans,
        # Only the files this run could write (ADR-036 D1).
        "sources": {outcome.path: outcome.before for outcome in run.files},
        "pack": pack.pack,
        "environ": {},
    }


def load(name: str) -> Case:
    """Scan one case and pair the result with its answer key."""
    root, config, projection = configured(name)
    return Case(
        name=name,
        root=root,
        key=yaml.safe_load((root / "ground_truth.yaml").read_text(encoding="utf-8")),
        scan=runner.scan(root, config, projection),
    )


def digest(scan: runner.Scan) -> str:
    """Hash everything a scan claims except `workers`, which `--jobs` is meant to change.

    Order is hashed too: unstable set iteration shows up as a reordering, not a missing row.
    """
    document = {
        "source": scan.source,
        "counts": scan.counts.model_dump(mode="json"),
        "findings": [row.model_dump(mode="json") for row in scan.findings],
        "bindings": [row.model_dump(mode="json") for row in scan.bindings],
        "manifests": scan.manifests.model_dump(mode="json"),
        "runtime": asdict(scan.runtime) if scan.runtime else None,
        "limitations": [asdict(row) for row in scan.limitations],
        "skipped": [asdict(row) for row in scan.skipped],
        "files": [
            [result.path, result.sha256, result.parsed, [asdict(r) for r in result.receivers]]
            for result in scan.results
        ],
    }
    return hashlib.sha256(json.dumps(document).encode("utf-8")).hexdigest()


def expected(row: dict[str, Any]) -> tuple[str, int, str, str, str | None]:
    """One key row's comparison key; `parse_error` drops `symbol`, which there holds source."""
    return (
        str(row["file"]),
        int(row["line"]),
        str(row["kind"]),
        str(row["confidence_reason"]),
        None if row["kind"] == "parse_error" else symbol(row["symbol"]),
    )


def _produced(finding: Finding) -> tuple[str, int, str, str, str | None]:
    return (
        finding.path,
        finding.line,
        finding.kind,
        finding.confidence_reason,
        None if finding.kind == "parse_error" else finding.symbol,
    )


def symbol(value: object) -> str:
    """A key's `symbol` without the quotes some fixtures put around it; the runtime emits none."""
    return str(value).strip('"')


def scan_status(verdict: str) -> str:
    """A key's fix-time `auto` is what a scan calls `eligible`."""
    return "eligible" if verdict == "auto" else verdict
