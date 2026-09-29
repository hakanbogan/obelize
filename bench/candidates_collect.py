"""Draw the benchmark candidate corpus, and scan what the draw adds.

`draw` (needs an authenticated `gh`, `git` and `obelize`) applies ADR-040's rules to the gate-1
frame, draws one repository per pack surface it misses, and writes `bench/candidates.yaml` plus
a scan record. A draw is dated, not reproducible, so its rows, counts and queries are committed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import candidates
import gate1_collect
import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "bench" / "candidates.yaml"
RESULTS = ROOT / "bench" / "results" / "candidates"
WORK = ROOT / "bench" / "work" / "candidates"

# One token per change, probed only if the corpus misses it; a zero count is about the probe.
PROBES: dict[str, str] = {
    "rename-import": "import",
    "configure-to-client": "configure",
    "generative-model-calls": "GenerativeModel",
    "embed-content": "embed_content",
    "embed-content-async": "embed_content_async",
    "upload-file": "upload_file",
    "get-file": "get_file",
    "delete-file": "delete_file",
    "list-files": "list_files",
    "list-models": "list_models",
    "get-model": "get_model",
    # Of the four flagged types, the one a caller writes by hand; the other three appear inside it.
    "flag-function-calling-types": "FunctionDeclaration",
    # What real chat code reaches for; the rarer `supported_generation_methods` would under-report.
    "flag-removed-object-attributes": "history",
    # The patterns reach the module by a string; a test double is the common one.
    "flag-legacy-module-reached-indirectly": "patch",
    # The out-of-scope symbol ordinary application code uses.
    "flag-out-of-scope-surfaces": "protos",
    # `language:python` never returns a manifest.
    "manifest-dependency": "filename:requirements.txt",
}

# Per surface: results examined, and how many may be cloned; both are published.
EXAMINE_CAP = 50
CLONE_CAP = 8

# Between non-search calls; searches use `gate1_collect.SEARCH_DELAY_S`.
CALL_DELAY_S = 0.3


def _api(*arguments: str) -> Any | None:
    """One `gh api` call, or `None` when refused: a failure is data, not a crash."""
    completed = subprocess.run(
        ["gh", "api", *arguments], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        return None
    return json.loads(completed.stdout)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _paths(full_name: str, sha: str) -> tuple[list[str], bool]:
    """Every path in the tree at `sha`, and whether GitHub truncated the answer."""
    tree = _api(f"repos/{full_name}/git/trees/{sha}?recursive=1")
    if tree is None:
        return [], False
    return [row["path"] for row in tree["tree"] if row["type"] == "blob"], bool(tree["truncated"])


def _disqualified(repository: dict[str, Any], owners: dict[str, int]) -> str | None:
    """The first rule `repository` fails, or `None`."""
    owner = repository["owner"]["login"]
    licence = (repository.get("license") or {}).get("spdx_id") or "none"
    if repository["fork"]:
        return "fork"
    if licence in {"none", "NOASSERTION"}:
        return "unlicensed"
    if owner in gate1_collect.DEV_CORPUS_OWNERS:
        return "development_corpus"
    if int(repository["size"]) > gate1_collect.SIZE_CAP_KB:
        return "larger_than_cap"
    if owners.get(owner, 0) >= candidates.MAX_PER_OWNER:
        return "owner_at_limit"
    return None


def _row(repository: dict[str, Any], sha: str, source: str) -> dict[str, Any]:
    paths, truncated = _paths(repository["full_name"], sha)
    row = {
        "full_name": repository["full_name"],
        "owner": repository["owner"]["login"],
        "url": repository["html_url"],
        "sha": sha,
        "license": (repository.get("license") or {}).get("spdx_id") or "none",
        # Recorded so docs/BENCHMARK.md's no-forks rule is checkable from committed data.
        "fork": bool(repository["fork"]),
        "archived": bool(repository["archived"]),
        "pushed_at": repository["pushed_at"],
        "stars": int(repository["stargazers_count"]),
        "size_kb": int(repository["size"]),
        "source": source,
        "tests": candidates.evidence(paths),
    }
    if truncated:
        row["tree_truncated"] = True
    return row


def _from_the_frame(
    frame: dict[str, Any], scanned: dict[str, list[dict[str, Any]]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    owners: dict[str, int] = {}
    for index, entry in enumerate(frame["repositories"], start=1):
        name = entry["full_name"]
        if not scanned.get(name):
            rejected.append({"full_name": name, "reason": "no_finding"})
            continue
        if candidates.vendors(scanned[name]):
            rejected.append({"full_name": name, "reason": "vendors_the_sdk"})
            continue
        repository = _api(f"repos/{name}")
        commit = None if repository is None else _api(f"repos/{name}/commits/{entry['sha']}")
        if repository is None or commit is None:
            rejected.append({"full_name": name, "reason": "gone"})
            continue
        reason = _disqualified(repository, owners)
        if reason is not None:
            rejected.append({"full_name": name, "reason": reason})
            continue
        owners[repository["owner"]["login"]] = owners.get(repository["owner"]["login"], 0) + 1
        kept.append(_row(repository, entry["sha"], "frame"))
        print(f"[{index}/{len(frame['repositories'])}] {name}: candidate", flush=True)
        time.sleep(CALL_DELAY_S)
    return kept, rejected


def _search(query: str) -> tuple[int, list[str]]:
    """Code search; a refusal is waited out once, then stops the draw: never a false `absent`."""
    payload = _api("-X", "GET", "search/code", "-f", f"q={query}", "-F", "per_page=100")
    if payload is None:
        time.sleep(65.0)
        payload = _api("-X", "GET", "search/code", "-f", f"q={query}", "-F", "per_page=100")
    if payload is None:
        raise SystemExit(f"code search refused twice: {query}")
    seen: list[str] = []
    for item in payload["items"]:
        name = item["repository"]["full_name"]
        if name not in seen:
            seen.append(name)
    time.sleep(gate1_collect.SEARCH_DELAY_S)
    return int(payload["total_count"]), seen


def _scan_one(name: str, sha: str, surface: candidates.Surface) -> dict[str, Any] | None:
    """Clone at `sha` and scan: the record, or `None` if either failed."""
    checkout = WORK / name.replace("/", "__")
    shutil.rmtree(checkout, ignore_errors=True)
    started = time.monotonic()
    try:
        gate1_collect._fetch({"full_name": name, "sha": sha}, checkout)
        found = gate1_collect._scan(checkout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError, OSError):
        shutil.rmtree(checkout, ignore_errors=True)
        return None
    record: dict[str, Any] = {
        "full_name": name,
        "sha": sha,
        "drawn_for": surface.change,
        "counts": found["counts"],
        "runtime": gate1_collect._runtime(checkout),
        # Line references to other people's code, never their source.
        "findings": [
            {key: value for key, value in row.items() if key != "evidence" and value is not None}
            for row in found["findings"]
        ],
        "seconds": round(time.monotonic() - started, 2),
    }
    shutil.rmtree(checkout, ignore_errors=True)
    return record


def _draw_for(
    surface: candidates.Surface, taken: set[str], owners: dict[str, int]
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    query = f"{gate1_collect.TERM} {PROBES[surface.change]} language:python"
    if PROBES[surface.change].startswith("filename:"):
        query = f"{gate1_collect.TERM} {PROBES[surface.change]}"
    hits, names = _search(query)
    entry: dict[str, Any] = {
        "change": surface.change,
        "query": query,
        "hits": hits,
        "examined": 0,
        "outcome": "absent" if hits == 0 else "no_eligible_result",
        "drawn": None,
        "skipped": [],
    }
    clones = 0
    for name in names[:EXAMINE_CAP]:
        entry["examined"] += 1
        if name in taken:
            entry["skipped"].append({"full_name": name, "reason": "already_a_candidate"})
            continue
        repository = _api(f"repos/{name}")
        if repository is None:
            entry["skipped"].append({"full_name": name, "reason": "gone"})
            continue
        reason = _disqualified(repository, owners)
        if reason is not None:
            entry["skipped"].append({"full_name": name, "reason": reason})
            continue
        if clones >= CLONE_CAP:
            entry["skipped"].append({"full_name": name, "reason": "clone_budget_spent"})
            continue
        head = _api(f"repos/{name}/commits/{repository['default_branch']}")
        if head is None:
            entry["skipped"].append({"full_name": name, "reason": "gone"})
            continue
        clones += 1
        record = _scan_one(name, head["sha"], surface)
        if record is None:
            entry["skipped"].append({"full_name": name, "reason": "scan_failed"})
            continue
        if candidates.vendors(record["findings"]):
            entry["skipped"].append({"full_name": name, "reason": "vendors_the_sdk"})
            continue
        if not candidates.exercises(record["findings"], surface):
            entry["skipped"].append({"full_name": name, "reason": "no_such_finding"})
            continue
        entry["outcome"] = "drawn"
        entry["drawn"] = name
        print(f"  {surface.change}: drew {name}", flush=True)
        return entry, _row(repository, head["sha"], f"surface:{surface.change}"), record
    print(f"  {surface.change}: {entry['outcome']} after {entry['examined']} result(s)", flush=True)
    return entry, None, None


def draw() -> None:
    frame = yaml.safe_load(gate1_collect.SAMPLE.read_text(encoding="utf-8"))
    gate1 = json.loads(gate1_collect.RESULTS.joinpath("scan.json").read_text(encoding="utf-8"))
    scanned = {row["full_name"]: row["findings"] for row in gate1["scanned"] if "error" not in row}
    kept, rejected = _from_the_frame(frame, scanned)
    owners: dict[str, int] = {}
    for candidate in kept:
        owners[candidate["owner"]] = owners.get(candidate["owner"], 0) + 1

    findings = dict(scanned)
    records: list[dict[str, Any]] = []
    drawn: list[dict[str, Any]] = []
    for surface in candidates.surfaces():
        if any(candidates.exercises(findings[one["full_name"]], surface) for one in kept):
            continue
        entry, added, record = _draw_for(surface, {one["full_name"] for one in kept}, owners)
        drawn.append(entry)
        if added is not None and record is not None:
            kept.append(added)
            owners[added["owner"]] = owners.get(added["owner"], 0) + 1
            findings[added["full_name"]] = record["findings"]
            records.append(record)

    RESULTS.mkdir(parents=True, exist_ok=True)
    RESULTS.joinpath("scan.json").write_text(
        json.dumps({**gate1_collect._provenance(), "scanned": records}, indent=2) + "\n",
        encoding="utf-8",
    )
    licensed = [
        row for row in frame["repositories"] if row["license"] not in {"none", "NOASSERTION"}
    ]
    document = {
        "drawn_at": _now(),
        "frame": {
            "sample": "bench/gate1/sample.yaml",
            "scan": "bench/results/gate1/scan.json",
            "queried_at": frame["queried_at"],
            "repositories": len(frame["repositories"]),
            "licensed": len(licensed),
        },
        "instrument": gate1_collect._provenance(),
        "max_per_owner": candidates.MAX_PER_OWNER,
        "size_cap_kb": gate1_collect.SIZE_CAP_KB,
        "examine_cap": EXAMINE_CAP,
        "clone_cap": CLONE_CAP,
        "candidates": kept,
        "rejected": rejected,
        "surfaces": drawn,
    }
    DATA.write_text(yaml.safe_dump(document, sort_keys=False, width=100), encoding="utf-8")
    print(f"{len(kept)} candidate(s), {len(rejected)} rejected -> {DATA.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw the benchmark candidate corpus.")
    parser.add_subparsers(dest="command", required=True).add_parser(
        "draw", help="apply the rules to the frame and draw for the surfaces it misses"
    )
    parser.parse_args()
    draw()


if __name__ == "__main__":
    main()
