"""Collect a round's row-level record from its run folders, for `bench/errors.py`.

Result files carry only counts; the rows live in each checkout's `.obelize/runs/`, which sits in
a temporary work tree the next round overwrites.

Usage::

    python bench/errors_collect.py            # writes bench/results/errors/round-1.json
    python bench/errors_collect.py --round 2

Run by hand while the round's work tree is still on disk; recreating it needs the network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cases
import run

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "bench" / "results" / "errors"

# Never `evidence`, which can quote a repository's source; `column` is unread.
FINDING_FIELDS = ("path", "line", "kind", "symbol", "confidence_reason", "scan_status", "bail")

WITHHELD_FIELDS = ("path", "line", "symbol", "bail", "caused_by")


def run_folder(checkout: Path) -> Path:
    """The case's single run folder; a second (a stale tree) leaves the published run ambiguous."""
    folders = sorted(path for path in (checkout / ".obelize" / "runs").glob("*") if path.is_dir())
    if len(folders) != 1:
        raise SystemExit(f"{checkout.name}: expected one run folder, found {len(folders)}")
    return folders[0]


def _same_run(case: run.Case, record: dict[str, Any], published: dict[str, Any]) -> None:
    """Refuse a run folder whose commit, pack or version differs from the published result's.

    Only the shared directory ties the two records together, so a stale work tree must fail here.
    """
    provenance = published["provenance"]
    for name, mine, theirs in (
        ("git_sha", record.get("git_sha"), case.sha),
        ("pack", (record.get("pack") or {}).get("sha256"), provenance["pack_sha256"]),
        ("obelize_version", record.get("obelize_version"), provenance["obelize_version"]),
    ):
        if mine != theirs:
            raise SystemExit(f"{case.id}: run folder {name} is {mine!r}, published {theirs!r}")


def _kept(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: row.get(field) for field in fields}


def applied(plan: dict[str, Any], record: dict[str, Any]) -> list[list[Any]]:
    """Where edits landed, as `[path, line]` pairs, computed as `bench/run.py` does."""
    landed = run.applied_positions(plan, [edit["path"] for edit in record.get("file_edits") or ()])
    return [[path, line] for path, line in sorted(landed)]


def collect(number: int) -> dict[str, Any]:
    """Every case and control, from its own run folder."""
    published = _published(number)
    work = run.WORK / f"round-{number}"
    collected: dict[str, Any] = {}
    for case in run.corpus():
        checkout = work / case.id
        if not checkout.is_dir():
            raise SystemExit(f"{case.id}: no checkout at {checkout}; the work tree is gone")
        folder = run_folder(checkout)
        record = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        _same_run(case, record, published[case.id])
        plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
        findings = json.loads((folder / "findings.json").read_text(encoding="utf-8"))
        collected[case.id] = {
            "run_id": record["run_id"],
            "exit_code": record["exit_code"],
            "findings": [_kept(row, FINDING_FIELDS) for row in findings["findings"]],
            "withheld": [_kept(row, WITHHELD_FIELDS) for row in record.get("withheld") or ()],
            "applied": applied(plan, record),
        }
    return {
        "round": number,
        "schema_version": 1,
        "obelize_version": sorted({r["provenance"]["obelize_version"] for r in published.values()}),
        "pack_sha256": sorted({r["provenance"]["pack_sha256"] for r in published.values()}),
        "cases": collected,
    }


def _published(number: int) -> dict[str, dict[str, Any]]:
    """The round's result files, which this record must agree with."""
    folder = run.RESULTS / f"round-{number}"
    found = {}
    for path in sorted(folder.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        found[str(record["case"])] = record
    if not found:
        raise SystemExit(f"{folder} holds no result; run the round before collecting it")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect a round's row-level record.")
    parser.add_argument(
        "--round", type=int, default=None, help="round number (default: the case file's)"
    )
    arguments = parser.parse_args(argv)
    number = arguments.round if arguments.round is not None else int(cases.load().cases["round"])
    document = collect(number)
    RESULTS.mkdir(parents=True, exist_ok=True)
    destination = RESULTS / f"round-{number}.json"
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = sum(len(case["withheld"]) for case in document["cases"].values())
    print(f"{destination.name}: {len(document['cases'])} cases, {rows} withheld rows")
    return 0


if __name__ == "__main__":  # pragma: no cover - the module is run by hand, once per round
    sys.exit(main())
