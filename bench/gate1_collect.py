"""Draw the gate-1 sample, and run `obelize scan` over it.

Data for Gate 1's zero-bail question (docs/PRODUCT.md), scored offline by
`bench/gate1_score.py`; `choose` names the repositories to hand-label. `dryrun` asks the same
frame what a `fix` dry run would write, for any pack, scored by `bench/dryrun_score.py`.

Usage::

    python -m bench.gate1_collect sample                 # writes bench/gate1/sample.yaml
    python -m bench.gate1_collect scan                   # writes bench/results/gate1/scan.json
    python -m bench.gate1_collect sample --pack P --term T   # the pack's frame (see `_frame`)
    python -m bench.gate1_collect dryrun --pack P            # bench/results/dryrun/<slug>.json

`<slug>` is the pack id with its slash written `__`.

`sample` needs an authenticated `gh`; `scan` and `dryrun` need `git` and `obelize`. Code search
re-ranks, so the frame is a dated draw: the drawn list is committed, not the query.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from packaging.utils import canonicalize_name

from obelize.packs import loader

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "bench" / "gate1" / "sample.yaml"
RESULTS = ROOT / "bench" / "results" / "gate1"
WORK = ROOT / "bench" / "work" / "gate1"
DRYRUN = ROOT / "bench" / "results" / "dryrun"

# The pack's prefilter token: an import query would miss `from google.generativeai import`.
TERM = "generativeai"

# Size strata: relevance favours short files, which more often have nothing bail.
BANDS: tuple[str, ...] = (
    "size:<1000",
    "size:1000..4000",
    "size:4000..16000",
    "size:>16000",
)

# The rules were written against these owners, so they are excluded.
DEV_CORPUS_OWNERS: frozenset[str] = frozenset({"llegomark", "eli64s", "log2timeline"})

# A larger repository costs more to fetch than it adds: skipped, and recorded as such.
SIZE_CAP_KB = 150_000

# Code search allows ten calls a minute; a 403 mid-draw would silently truncate a band.
SEARCH_DELAY_S = 7.0

# A timeout is recorded as an error, never retried: a retry changes what was measured.
FETCH_TIMEOUT_S = 300
SCAN_TIMEOUT_S = 900
FIX_TIMEOUT_S = 900

PAGES = 4
PER_PAGE = 100


def _gh(*arguments: str) -> Any:
    """One `gh api` call, decoded. A failure is fatal: a partial draw is not a draw."""
    completed = subprocess.run(
        ["gh", "api", *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"gh api {' '.join(arguments)} failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def _band_total(band: str, term: str) -> int:
    payload = _gh(
        "-X", "GET", "search/code", "-f", f"q={term} language:python {band}", "-F", "per_page=1"
    )
    return int(payload["total_count"])


def _band_hits(band: str, term: str) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for page in range(1, PAGES + 1):
        payload = _gh(
            "-X",
            "GET",
            "search/code",
            "-f",
            f"q={term} language:python {band}",
            "-F",
            f"per_page={PER_PAGE}",
            "-F",
            f"page={page}",
        )
        for item in payload["items"]:
            repository = item["repository"]
            seen.setdefault(
                repository["full_name"],
                {
                    "full_name": repository["full_name"],
                    "owner": repository["owner"]["login"],
                    "fork": bool(repository["fork"]),
                    "first_hit": item["path"],
                },
            )
        if len(payload["items"]) < PER_PAGE:
            break
        time.sleep(SEARCH_DELAY_S)
    return list(seen.values())


def _systematic(rows: list[dict[str, Any]], wanted: int) -> list[dict[str, Any]]:
    """Every k-th row across the band's depth, not its relevance-biased top; no top-up if short."""
    if wanted <= 0 or not rows:
        return []
    step = max(1, len(rows) // wanted)
    return [rows[index] for index in range(0, len(rows), step)][:wanted]


def _metadata(full_name: str) -> dict[str, Any]:
    repository = _gh(f"repos/{full_name}")
    licence = repository.get("license") or {}
    branch = repository["default_branch"]
    head = _gh(f"repos/{full_name}/commits/{branch}")
    return {
        "full_name": full_name,
        "owner": repository["owner"]["login"],
        "url": repository["html_url"],
        "sha": head["sha"],
        "default_branch": branch,
        "license": licence.get("spdx_id") or "none",
        "size_kb": int(repository["size"]),
        "stars": int(repository["stargazers_count"]),
        "archived": bool(repository["archived"]),
        "pushed_at": repository["pushed_at"],
    }


def _frame(pack: str) -> Path:
    """The Gemini frame keeps its place; another pack's is `bench/gate1/<slug>/sample.yaml`."""
    from .run import DEFAULT_PACK

    if pack == DEFAULT_PACK:
        return SAMPLE
    return ROOT / "bench" / "gate1" / pack.replace("/", "__") / "sample.yaml"


def sample(total: int, pack: str, term: str) -> None:
    totals = {}
    for band in BANDS:
        totals[band] = _band_total(band, term)
        time.sleep(SEARCH_DELAY_S)
    population = sum(totals.values())
    # The rounding remainder goes to the largest band so the allocation sums to `total`.
    allocation = {band: round(total * totals[band] / population) for band in BANDS}
    largest = max(BANDS, key=lambda band: totals[band])
    allocation[largest] += total - sum(allocation.values())

    chosen: list[dict[str, Any]] = []
    owners: set[str] = set(DEV_CORPUS_OWNERS)
    rejected: list[dict[str, Any]] = []
    drawn: dict[str, int] = {}
    for band in BANDS:
        hits = _band_hits(band, term)
        drawn[band] = len(hits)
        kept = 0
        for row in _systematic(hits, allocation[band] * 3):
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
            if reason is not None:
                rejected.append({"full_name": row["full_name"], "reason": reason})
                continue
            meta = _metadata(row["full_name"])
            if meta["size_kb"] > SIZE_CAP_KB:
                rejected.append(
                    {"full_name": row["full_name"], "reason": f"larger than {SIZE_CAP_KB} KB"}
                )
                continue
            meta["band"] = band
            owners.add(meta["owner"])
            chosen.append(meta)
            kept += 1
        time.sleep(SEARCH_DELAY_S)

    document = {
        "queried_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pack": pack,
        "term": term,
        "bands": [
            {
                "band": band,
                "population": totals[band],
                "allocated": allocation[band],
                "drawn": drawn[band],
            }
            for band in BANDS
        ],
        "population": population,
        "size_cap_kb": SIZE_CAP_KB,
        "excluded_owners": sorted(DEV_CORPUS_OWNERS),
        "rejected": rejected,
        "repositories": chosen,
    }
    frame = _frame(pack)
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_text(yaml.safe_dump(document, sort_keys=False, width=100), encoding="utf-8")
    print(f"{len(chosen)} repositories -> {frame.relative_to(ROOT)}")


def fetch(entry: dict[str, Any], into: Path) -> None:
    """A one-commit checkout at the pinned SHA, with the `.git` a scan reads through."""
    into.mkdir(parents=True)
    url = f"https://github.com/{entry['full_name']}.git"
    for arguments in (
        ["init", "-q"],
        ["remote", "add", "origin", url],
        ["fetch", "-q", "--depth", "1", "origin", entry["sha"]],
        ["checkout", "-q", "FETCH_HEAD"],
    ):
        subprocess.run(
            ["git", "-C", str(into), *arguments],
            check=True,
            capture_output=True,
            timeout=FETCH_TIMEOUT_S,
        )


def declared_runtime(checkout: Path) -> dict[str, Any]:
    """The declared Python via the shipped `scan/runtime.py`; `run.json` keeps only the verdict."""
    from obelize.models import Config
    from obelize.scan import parse, runtime, walker

    from .run import DEFAULT_PACK

    selection = walker.walk(checkout, Config())
    spec = loader.to_scan_spec(loader.load(DEFAULT_PACK))
    floor = runtime.detect(selection.manifests, parse.disk(checkout, Config()), spec)
    if floor.declared is None:
        return {"declared": None, "blocked": False}
    return {
        "declared": floor.declared.declared,
        "path": floor.declared.path,
        "blocked": floor.blocked is not None,
    }


def _cli(arguments: list[str], timeout: int) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "obelize.cli", *arguments, "--json"],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"exit {completed.returncode}: {completed.stderr.strip()[:200]}")
    return json.loads(completed.stdout)  # type: ignore[no-any-return]


def scan_checkout(checkout: Path) -> dict[str, Any]:
    return _cli(["scan", "--repo", str(checkout)], SCAN_TIMEOUT_S)


def _fix(checkout: Path, pack: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """A dry run with no model: its plan, its run record for what a pack held back, and the rows
    it read.
    """
    arguments = ["fix", "--repo", str(checkout), "--pack", pack, "--model", "none"]
    plan = _cli(arguments, FIX_TIMEOUT_S)
    folder = max((checkout / ".obelize" / "runs").glob("*/run.json")).parent
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    return plan, run, json.loads((folder / "findings.json").read_text(encoding="utf-8"))["findings"]


def provenance(pack: str | None = None) -> dict[str, Any]:
    """The instrument beside the number; CI never re-runs these scans.

    `spec_sha256` hashes what `scan/*` and `impact/*` read (ADR-026 D8): only its change needs a
    re-run. `pack_sha256` names the file. The pack is Gemini's unless one is named.
    """
    from obelize import __version__

    from .run import DEFAULT_PACK

    pack = pack or DEFAULT_PACK
    loaded = loader.load(pack)
    return {
        "obelize_version": __version__,
        "pack": pack,
        "pack_sha256": loaded.sha256,
        "spec_sha256": loader.spec_digest(loader.to_scan_spec(loaded)),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "os": platform.system(),
    }


# One repository that fails is a record, not the end of an hour's draw.
RECORDED = (
    subprocess.CalledProcessError,
    subprocess.TimeoutExpired,
    RuntimeError,
    OSError,
    ValueError,
    LookupError,
)


def _each(
    entries: list[dict[str, Any]],
    measure: Callable[[dict[str, Any], Path], None],
    describe: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    """Fetch each repository at its pinned commit, `measure` it into its record, and delete it."""
    records = []
    for index, entry in enumerate(entries, start=1):
        checkout = WORK / entry["full_name"].replace("/", "__")
        shutil.rmtree(checkout, ignore_errors=True)
        record: dict[str, Any] = {
            "full_name": entry["full_name"],
            "sha": entry["sha"],
            "band": entry["band"],
        }
        started = time.monotonic()
        try:
            fetch(entry, checkout)
            measure(record, checkout)
        except RECORDED as error:
            record["error"] = f"{type(error).__name__}: {error}"[:300]
        record["seconds"] = round(time.monotonic() - started, 2)
        shutil.rmtree(checkout, ignore_errors=True)
        records.append(record)
        state = record.get("error") or describe(record)
        print(f"[{index}/{len(entries)}] {entry['full_name']}: {state}", flush=True)
    return records


def scan(only: str | None) -> None:
    document = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    entries = [row for row in document["repositories"] if only is None or row["full_name"] == only]
    RESULTS.mkdir(parents=True, exist_ok=True)

    def measure(record: dict[str, Any], checkout: Path) -> None:
        findings = scan_checkout(checkout)
        record["counts"] = findings["counts"]
        record["runtime"] = declared_runtime(checkout)
        # Line references to other people's code, never their source.
        record["findings"] = [
            {
                key: value
                for key, value in finding.items()
                if key != "evidence" and value is not None
            }
            for finding in findings["findings"]
        ]

    records = _each(entries, measure, lambda record: f"{record['counts']['findings']} finding(s)")
    out = RESULTS / "scan.json"
    out.write_text(
        json.dumps({**provenance(), "scanned": records}, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"{len(records)} record(s) -> {out.relative_to(ROOT)}")


def dryrun(pack: str) -> None:
    """Per repository: the files a dry run would write, and every row it held back, with why.

    Never a subset: a retry of one repository would replace the record of the other seventy-nine.
    """
    document = yaml.safe_load(_frame(pack).read_text(encoding="utf-8"))
    DRYRUN.mkdir(parents=True, exist_ok=True)

    legacy = canonicalize_name(loader.to_scan_spec(loader.load(pack)).legacy_distribution)

    def measure(record: dict[str, Any], checkout: Path) -> None:
        plan, run, found = _fix(checkout, pack)
        record["blocked"] = run["packs"][0]["blocked"]
        # The scanner's own "used": a manifest row or a mention in a comment is no usage.
        record["used"] = sum(
            1 for row in found if row["kind"] != "manifest" and row["scan_status"] != "not_a_usage"
        )
        # Declarations of the legacy distribution, which tell a pin that is missing from one that is
        # out of range; the new distribution's own row (`manifest_code_mismatch`) is not one.
        record["manifests"] = sum(
            1
            for row in found
            if row["kind"] == "manifest" and canonicalize_name(row["symbol"] or "") == legacy
        )
        record["files"] = len(plan["files"])
        record["withheld"] = [
            {key: row[key] for key in ("path", "line", "symbol", "bail", "caused_by")}
            for row in run["withheld"]
        ]

    records = _each(
        document["repositories"],
        measure,
        lambda record: f"{record['files']} file(s), {len(record['withheld'])} withheld",
    )
    out = DRYRUN / f"{pack.replace('/', '__')}.json"
    out.write_text(
        json.dumps(
            {
                **provenance(pack),
                "frame": _frame(pack).relative_to(ROOT).as_posix(),
                "dry_run": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(records)} record(s) -> {out.relative_to(ROOT)}")


# Token files per labelled repository: more get labelled worse; one cannot disagree with itself.
LABEL_FILES = (2, 8)


def _token_files(checkout: Path) -> list[str]:
    found = []
    for path in sorted(checkout.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover - a broken symlink in someone's tree
            continue
        if TERM in text:
            found.append(str(path.relative_to(checkout)))
    return found


def choose(extra_band: str) -> None:
    """Name repositories to hand-label by a fixed rule; keys must predate `scan` to mean anything.

    Per band in frame order, the first with `LABEL_FILES` token files, plus one from `extra_band`.
    """
    document = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    low, high = LABEL_FILES
    wanted = dict.fromkeys(BANDS, 1)
    wanted[extra_band] += 1
    for band in BANDS:
        for entry in [row for row in document["repositories"] if row["band"] == band]:
            if wanted[band] == 0:
                break
            checkout = WORK / entry["full_name"].replace("/", "__")
            shutil.rmtree(checkout, ignore_errors=True)
            try:
                fetch(entry, checkout)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
                print(f"    {entry['full_name']}: fetch failed ({type(error).__name__})")
                shutil.rmtree(checkout, ignore_errors=True)
                continue
            files = _token_files(checkout)
            if low <= len(files) <= high:
                wanted[band] -= 1
                print(f"CHOSEN {entry['full_name']} [{band}] {len(files)} file(s) -> {checkout}")
                for name in files:
                    print(f"    {name}")
            else:
                print(f"    {entry['full_name']}: {len(files)} file(s), outside {low}-{high}")
                shutil.rmtree(checkout, ignore_errors=True)


def main() -> None:
    from .run import DEFAULT_PACK

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    drawer = sub.add_parser("sample", help="draw the frame from GitHub code search")
    drawer.add_argument("--total", type=int, default=80, help="repositories to draw (default: 80)")
    drawer.add_argument("--pack", default=None, help="the pack the frame is for (default: Gemini)")
    drawer.add_argument("--term", default=None, help="its code-search term, required with --pack")
    runner = sub.add_parser("scan", help="fetch and scan every repository in the frame")
    runner.add_argument("--only", default=None, help="one repository full name, for a retry")
    dryrunner = sub.add_parser("dryrun", help="fetch every repository and plan a fix with no model")
    dryrunner.add_argument("--pack", default=None, help="the pack to plan (default: Gemini)")
    picker = sub.add_parser("choose", help="name the repositories to hand-label")
    picker.add_argument(
        "--extra-band", default="size:4000..16000", help="the band that contributes the fifth"
    )
    arguments = parser.parse_args()
    if arguments.command == "sample":
        if (arguments.pack is None) != (arguments.term is None):
            parser.error("--pack and --term go together: the default is Gemini's pair")
        sample(arguments.total, arguments.pack or DEFAULT_PACK, arguments.term or TERM)
    elif arguments.command == "dryrun":
        dryrun(arguments.pack or DEFAULT_PACK)
    elif arguments.command == "choose":
        choose(arguments.extra_band)
    else:
        scan(arguments.only)


if __name__ == "__main__":
    main()
