"""Draw the frames of the pack-less `obelize upgrade`, and run its dry run over them.

Data for the benchmark of `obelize upgrade <distribution> --from A --to B` (docs/UPGRADING.md),
scored offline by `bench/upgrade_score.py`. A frame is one migration's public repositories whose
code still uses the old API, since a repository already on the new one says nothing. The pack is
made once per migration from the two releases and every repository is planned with it. Nothing is
written, tried or installed, and no file of a clone is run. `upgrade` plans a file at a time, so a
repository with a place left is `partial` where it was `held` (the record's `unit` says which).

Usage::

    python -m bench.upgrade_collect sample                   # bench/upgrade/<slug>/sample.yaml
    python -m bench.upgrade_collect run                      # bench/results/upgrade/<slug>.json
    python -m bench.upgrade_collect run -m SLUG --only O/R --out DIR   # a trial, not a record

`sample` needs an authenticated `gh`; `run` needs `git` and the package index. Code search
re-ranks, so a frame is a dated draw: the drawn list is committed, not the query.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

import yaml
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from obelize import __version__, index, net
from obelize.models import ATOMICITY_BAIL

from . import gate1_collect, read_yaml

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / "bench" / "upgrade"
RESULTS = ROOT / "bench" / "results" / "upgrade"
WORK = ROOT / "bench" / "work" / "upgrade"

# The repositories the mode was tried on while it was written, so they are not drawn.
DEV_CORPUS_OWNERS: frozenset[str] = frozenset({"BreezeWhite", "ga4gh", "LinXueyuanStdio"})

# A hit inside a vendored copy or a committed virtualenv is another project's code, not a user's.
COPIES: frozenset[str] = frozenset(
    {"vendor", "_vendor", "vendored", "site-packages", "third_party"}
)

# A timeout is recorded as an error, never retried: a retry changes what was measured.
UPGRADE_TIMEOUT_S = 900

# The bail of a place the pack only flags, copied so a package change cannot silently re-grade.
FLAGGED = "flag_only_surface"

PER_FRAME = 20


class Migration(NamedTuple):
    distribution: str
    old: str  # the release line the code is written for, as a specifier; the newest in it is used
    new: str
    term: str  # code search finds the old API with it
    why: str


MIGRATIONS: dict[str, Migration] = {
    "pydantic-1-to-2": Migration(
        "pydantic",
        "==1.10.*",
        "==2.12.*",
        '"from pydantic import validator"',
        "Version 2 deprecates `validator` for `field_validator`, so a file that imports it is "
        "written for 1.x. The phrase is the whole import line: an import of more names is not "
        "matched.",
    ),
    "sqlalchemy-1-to-2": Migration(
        "sqlalchemy",
        "==1.4.*",
        "==2.0.*",
        '"from sqlalchemy.ext.declarative import declarative_base"',
        "Version 2 moves `declarative_base` to `sqlalchemy.orm`; the old import is the first "
        "line of the models of a project written for 1.x.",
    ),
    "urllib3-1-to-2": Migration(
        "urllib3",
        "==1.26.*",
        ">=2,<3",
        'method_whitelist "urllib3.util.retry import Retry"',
        "Version 2 removes the `Retry` keyword `method_whitelist` (`allowed_methods` since "
        "1.26), so only code written for 1.x spells it. The word alone matches mostly the "
        "copies of urllib3 inside other projects, which do not import `Retry` as a user does.",
    ),
    "pandas-2-to-3": Migration(
        "pandas",
        ">=2,<3",
        ">=3,<4",
        "infer_datetime_format",
        "The keyword of `read_csv` and `to_datetime` is gone from pandas 3, so only code written "
        "for 2.x or older passes it.",
    ),
}


def latest(distribution: str, line: str) -> str:
    """The newest release of `distribution` in `line`, not withdrawn and not a pre-release."""
    project = index.project(net.Fetcher(index="https://pypi.org"), distribution)
    found = {
        one.version
        for one in project.files
        if one.yanked is None
        and not one.version.is_prerelease
        and one.version in SpecifierSet(line)
    }
    return str(max(found))


def sample(slug: str, total: int) -> None:
    migration = MIGRATIONS[slug]
    # Asked first: an unreachable index must not cost the draw.
    old, new = (
        latest(migration.distribution, migration.old),
        latest(migration.distribution, migration.new),
    )
    bands = gate1_collect.BANDS
    delay = gate1_collect.SEARCH_DELAY_S
    totals = {}
    for band in bands:
        totals[band] = gate1_collect.band_total(band, migration.term)
        time.sleep(delay)
    population = sum(totals.values())
    # The rounding remainder goes to the largest band so the allocation sums to `total`.
    allocation = {band: round(total * totals[band] / population) for band in bands}
    largest = max(bands, key=lambda band: totals[band])
    allocation[largest] += total - sum(allocation.values())

    chosen: list[dict[str, Any]] = []
    owners: set[str] = set(DEV_CORPUS_OWNERS)
    rejected: list[dict[str, Any]] = []
    drawn: dict[str, int] = {}
    for band in bands:
        hits = gate1_collect.band_hits(band, migration.term)
        drawn[band] = len(hits)
        kept = 0
        for row in gate1_collect.systematic(hits, allocation[band] * 3):
            if kept >= allocation[band]:
                break
            reason = None
            if row["fork"]:
                reason = "fork"
            elif row["owner"] in owners:
                reason = (
                    "owner already sampled"
                    if row["owner"] not in DEV_CORPUS_OWNERS
                    else "development corpus owner"
                )
            elif COPIES & {part.lower() for part in PurePosixPath(row["first_hit"]).parts}:
                reason = "the hit is inside a copy of the library"
            if reason is not None:
                rejected.append({"full_name": row["full_name"], "reason": reason})
                continue
            meta = gate1_collect.metadata(row["full_name"])
            if meta["size_kb"] > gate1_collect.SIZE_CAP_KB:
                rejected.append(
                    {
                        "full_name": row["full_name"],
                        "reason": f"larger than {gate1_collect.SIZE_CAP_KB} KB",
                    }
                )
                continue
            meta["band"] = band
            owners.add(meta["owner"])
            chosen.append(meta)
            kept += 1
        time.sleep(delay)

    document = {
        "queried_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "distribution": migration.distribution,
        "from": old,
        "to": new,
        "term": migration.term,
        "why": migration.why,
        "bands": [
            {
                "band": band,
                "population": totals[band],
                "allocated": allocation[band],
                "drawn": drawn[band],
            }
            for band in bands
        ],
        "population": population,
        "size_cap_kb": gate1_collect.SIZE_CAP_KB,
        "excluded_owners": sorted(DEV_CORPUS_OWNERS),
        "rejected": rejected,
        "repositories": chosen,
    }
    frame = FRAMES / slug / "sample.yaml"
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_text(yaml.safe_dump(document, sort_keys=False, width=100), encoding="utf-8")
    print(f"{len(chosen)} repositories -> {frame.relative_to(ROOT)}")


def _upgrade(
    checkout: Path, frame: dict[str, Any], environ: dict[str, str], *, offline: bool
) -> subprocess.CompletedProcess[str]:
    """The dry run of `upgrade`; with no `--apply` it has no trial and asks no model or agent."""
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "obelize.cli",
            "upgrade",
            frame["distribution"],
            "--from",
            frame["from"],
            "--to",
            frame["to"],
            "--repo",
            str(checkout),
            *(["--offline"] if offline else []),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=UPGRADE_TIMEOUT_S,
        env=environ,
    )


def _documents(checkout: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """The newest run folder's record, the rows it read and its plan."""
    folder = max((checkout / ".obelize" / "runs").glob("*/run.json")).parent
    run, found, plan = (
        json.loads((folder / name).read_text(encoding="utf-8"))
        for name in ("run.json", "findings.json", "plan.json")
    )
    return run, found["findings"], plan


def written(usages: list[dict[str, Any]], withheld: list[dict[str, Any]]) -> int:
    """The usages no withheld row stands for: the plan holds them."""
    held = Counter((row["path"], row["line"], row["symbol"]) for row in withheld)
    count = 0
    for row in usages:
        key = (row["path"], row["line"], row["symbol"])
        if held[key]:
            held[key] -= 1
        else:
            count += 1
    return count


def synthesize(frame: dict[str, Any], root: Path, environ: dict[str, str]) -> dict[str, Any]:
    """Make the pack once: `upgrade` on an empty repository makes it and keeps it in the cache,
    which every later run reads.
    """
    empty = root / "empty"
    empty.mkdir(parents=True)
    subprocess.run(["git", "-C", str(empty), "init", "-q"], check=True, capture_output=True)
    started = time.monotonic()
    completed = _upgrade(empty, frame, environ, offline=False)
    seconds = round(time.monotonic() - started, 2)
    if completed.returncode != 0:
        raise RuntimeError(
            f"no pack: exit {completed.returncode}: {completed.stderr.strip()[-300:]}"
        )
    summary, _, _ = _documents(empty)
    made = read_yaml(next((root / "cache").rglob("pack.yaml")))
    kinds = {
        symbol: change["kind"]
        for change in made["changes"]
        for symbol in (
            change["params"].get("renamed")
            or change["params"].get("members")
            or change["params"].get("symbols")
            or ()
        )
    }
    return {
        "id": summary["packs"][0]["id"],
        "sha256": summary["packs"][0]["sha256"],
        "seconds": seconds,
        "note": next(line for line in completed.stderr.splitlines() if line.startswith("Moving ")),
        "kinds": kinds,
    }


def provenance(frame: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """The instrument beside the number; CI never re-runs these plans."""
    return {
        "obelize_version": __version__,
        "distribution": frame["distribution"],
        "from": frame["from"],
        "to": frame["to"],
        "pack": pack["id"],
        "pack_sha256": pack["sha256"],
        # What the plan is written by: `upgrade` writes a file at a time where one distribution
        # holds both APIs. A record without it is of a release that wrote a repository whole.
        "unit": "file",
        "synth_seconds": pack["seconds"],
        "synth_note": pack["note"],
        "python": platform.python_version(),
        "machine": platform.machine(),
        "os": platform.system(),
    }


def run(frame_path: Path, out: Path, only: list[str] | None) -> None:
    """Per repository: what the pack found, what its rules write, what it flags, and whether the
    whole plan would be written. Never a subset in the committed record (see `main`).
    """
    frame = read_yaml(frame_path)
    slug = frame_path.parent.name
    root = WORK / slug
    shutil.rmtree(root, ignore_errors=True)
    # Neither the person's configuration (a model, an agent) nor their cache decides the result.
    environ = {
        **{key: value for key, value in os.environ.items() if not key.startswith("OBELIZE_")},
        "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_CONFIG_HOME": str(root / "config"),
    }
    pack = synthesize(frame, root, environ)
    legacy = canonicalize_name(frame["distribution"])

    def measure(record: dict[str, Any], checkout: Path) -> None:
        completed = _upgrade(checkout, frame, environ, offline=True)
        if completed.returncode != 0:
            raise RuntimeError(f"exit {completed.returncode}: {completed.stderr.strip()[-200:]}")
        summary, found, plan = _documents(checkout)
        if summary["packs"][0]["sha256"] != pack["sha256"]:
            raise RuntimeError("planned with another pack than the one made")
        # The scanner's own "used": a manifest row or a mention in a comment is no usage.
        usages = [
            row
            for row in found
            if row["kind"] != "manifest" and row["scan_status"] != "not_a_usage"
        ]
        record["blocked"] = summary["packs"][0]["blocked"]
        record["manifests"] = sum(
            1
            for row in found
            if row["kind"] == "manifest" and canonicalize_name(row["symbol"] or "") == legacy
        )
        record["used"] = len(usages)
        # A rule writes a row the scanner passed, or one held only for another row's sake.
        record["rules"] = dict(
            Counter(
                pack["kinds"].get(row["symbol"], "unlisted")
                for row in usages
                if row["scan_status"] == "eligible" or row["bail"] == ATOMICITY_BAIL
            )
        )
        record["flagged"] = sum(1 for row in usages if row["bail"] == FLAGGED)
        record["written"] = written(usages, summary["withheld"])
        record["files"] = len(plan["files"])
        record["withheld"] = [
            {key: row[key] for key in ("path", "line", "symbol", "bail", "caused_by")}
            for row in summary["withheld"]
        ]
        record["plan_seconds"] = round(summary["timings"]["total_ms"] / 1000, 2)

    entries = [row for row in frame["repositories"] if not only or row["full_name"] in only]
    records = gate1_collect.each(
        entries,
        measure,
        lambda record: (
            f"{record['used']} usage(s), {record['files']} file(s), "
            f"{len(record['withheld'])} withheld"
        ),
        root / "repos",
    )
    shutil.rmtree(root, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{slug}.json"
    target.write_text(
        json.dumps(
            {
                **provenance(frame, pack),
                "frame": frame_path.relative_to(ROOT).as_posix(),
                "upgrade": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(records)} record(s) -> {target}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    drawer = sub.add_parser("sample", help="draw the frames from GitHub code search")
    runner = sub.add_parser("run", help="fetch every repository of the frames and plan its upgrade")
    for command in (drawer, runner):
        command.add_argument(
            "-m", "--migration", action="append", choices=list(MIGRATIONS), help="default: all"
        )
    drawer.add_argument(
        "--total",
        type=int,
        default=PER_FRAME,
        help=f"repositories per frame (default: {PER_FRAME})",
    )
    runner.add_argument("--only", action="append", help="a repository full name, for a trial")
    runner.add_argument("--out", type=Path, default=RESULTS, help="where the records go")
    arguments = parser.parse_args()
    if arguments.command == "run" and arguments.only and arguments.out == RESULTS:
        parser.error("--only measures part of a frame: give --out, or the record would be partial")
    failed = []
    for slug in arguments.migration or MIGRATIONS:
        if arguments.command == "sample":
            sample(slug, arguments.total)
            continue
        try:
            run(FRAMES / slug / "sample.yaml", arguments.out, arguments.only)
        except RuntimeError as error:  # a pack that cannot be made is that frame's whole result
            print(f"{slug}: {error}", file=sys.stderr)
            failed.append(slug)
    if failed:
        raise SystemExit(f"no record for {', '.join(failed)}")


if __name__ == "__main__":
    main()
