"""Draw the two things the case set needs and the candidate corpus does not hold.

Test-suite repositories and scan-confirmed negative controls, drawn under ADR-040's rules
into their own file.

Usage::

    python bench/cases_collect.py draw
    python bench/cases_collect.py checkout owner/name

`draw` needs an authenticated `gh`, `git` and `obelize`, and is dated, not reproducible.
`checkout` leaves one repository at its pinned SHA in the gitignored `bench/work/cases/`.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, NamedTuple

import candidates
import candidates_collect
import cases
import gate1_collect
import yaml
from gate1_score import ACTIONABLE_KINDS

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "bench" / "cases_draws.yaml"
RESULTS = ROOT / "bench" / "results" / "cases"
WORK = ROOT / "bench" / "work" / "cases"

# Tests that name the SDK may cover the change, which `verified_success` needs.
TESTS_QUERY = f"{gate1_collect.TERM} path:tests language:python"

# Each kept repository costs a hand-written answer key.
TESTS_KEEP = 5

# Above `candidates_collect.CLONE_CAP`: licensing rejects over half of the results.
TESTS_CLONE_CAP = 12


class Control(NamedTuple):
    id: str
    shape: str
    query: str
    # Regex the checkout must match, or the search hit something else.
    witness: str
    # A `WITNESS_GLOBS` key.
    where: str


# Both Vertex origins: only the import tells their live `GenerativeModel`s apart.
CONTROLS: tuple[Control, ...] = (
    Control(
        id="already-migrated",
        shape="already on the new SDK",
        query='"from google import genai" language:python',
        witness=r"from\s+google\s+import\s+genai",
        where="python",
    ),
    Control(
        id="vertex-generative-models",
        shape="vertexai.generative_models",
        query='"from vertexai.generative_models import" language:python',
        witness=r"\bvertexai\.generative_models\b|from\s+vertexai\.generative_models\s+import",
        where="python",
    ),
    Control(
        id="vertex-preview",
        shape="vertexai.preview.generative_models",
        query='"vertexai.preview.generative_models" language:python',
        witness=r"\bvertexai\.preview\.generative_models\b",
        where="python",
    ),
    Control(
        id="prose-only",
        shape="named only in prose",
        # The full name: the bare `generativeai` token also matches URL slugs.
        query='"google-generativeai" language:markdown',
        witness=r"google[-.]generativeai",
        where="prose",
    ),
)

# Prose means docs: a match in `requirements.txt` or a lock file is a dependency.
WITNESS_GLOBS: dict[str, tuple[str, ...]] = {
    "python": ("*.py",),
    "prose": ("*.md", "*.rst"),
}

# `.obelize` too, though `_scan` deletes it: a scan's own report is never a witness.
SKIP_DIRECTORIES: frozenset[str] = frozenset(
    {".git", ".obelize", "__pycache__", "node_modules", "site-packages", ".venv"}
)


def _slug(full_name: str) -> str:
    return full_name.replace("/", "__")


def _fetch(full_name: str, sha: str, into: Path) -> None:
    shutil.rmtree(into, ignore_errors=True)
    gate1_collect._fetch({"full_name": full_name, "sha": sha}, into)


def _scan(full_name: str, sha: str, drawn_for: str) -> dict[str, Any] | None:
    """Clone at `sha` and scan, keeping the checkout; `None` on failure."""
    checkout = WORK / _slug(full_name)
    started = time.monotonic()
    try:
        _fetch(full_name, sha, checkout)
        found = gate1_collect._scan(checkout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError, OSError):
        shutil.rmtree(checkout, ignore_errors=True)
        return None
    # Else the scan's run folder is read back as the repository's own content.
    shutil.rmtree(checkout / ".obelize", ignore_errors=True)
    return {
        "full_name": full_name,
        "sha": sha,
        "drawn_for": drawn_for,
        "counts": found["counts"],
        "runtime": gate1_collect._runtime(checkout),
        # Line references to other people's code, never their source.
        "findings": [
            {key: value for key, value in row.items() if key != "evidence" and value is not None}
            for row in found["findings"]
        ],
        "seconds": round(time.monotonic() - started, 2),
    }


def _witness(checkout: Path, pattern: str, where: str) -> str | None:
    """The first matching `path:line`, or `None`."""
    matcher = re.compile(pattern)
    found = {one for glob in WITNESS_GLOBS[where] for one in checkout.rglob(glob)}
    for path in sorted(found):
        if not path.is_file() or path.is_symlink():
            continue
        if SKIP_DIRECTORIES & set(path.relative_to(checkout).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if matcher.search(line):
                return f"{path.relative_to(checkout).as_posix()}:{number}"
    return None


def _head(full_name: str, repository: dict[str, Any]) -> str | None:
    commit = candidates_collect._api(f"repos/{full_name}/commits/{repository['default_branch']}")
    if commit is None:
        return None
    return str(commit["sha"])


def _eligible(
    name: str, taken: set[str], owners: dict[str, int], entry: dict[str, Any]
) -> dict[str, Any] | None:
    """The repository, or `None` after recording the skip reason."""
    if name in taken:
        entry["skipped"].append({"full_name": name, "reason": "already_a_candidate"})
        return None
    repository = candidates_collect._api(f"repos/{name}")
    if repository is None:
        entry["skipped"].append({"full_name": name, "reason": "gone"})
        return None
    reason = candidates_collect._disqualified(repository, owners)
    if reason is not None:
        entry["skipped"].append({"full_name": name, "reason": reason})
        return None
    return dict(repository)


def draw_test_suites(taken: set[str], owners: dict[str, int]) -> tuple[dict[str, Any], list[Any]]:
    hits, names = candidates_collect._search(TESTS_QUERY)
    entry: dict[str, Any] = {
        "query": TESTS_QUERY,
        "hits": hits,
        "examined": 0,
        "outcome": "absent" if hits == 0 else "no_eligible_result",
        "keep": TESTS_KEEP,
        "drawn": [],
        "skipped": [],
    }
    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    clones = 0
    for name in names[: candidates_collect.EXAMINE_CAP]:
        if len(rows) >= TESTS_KEEP:
            break
        entry["examined"] += 1
        repository = _eligible(name, taken, owners, entry)
        if repository is None:
            continue
        if clones >= TESTS_CLONE_CAP:
            entry["skipped"].append({"full_name": name, "reason": "clone_budget_spent"})
            continue
        sha = _head(name, repository)
        if sha is None:
            entry["skipped"].append({"full_name": name, "reason": "gone"})
            continue
        clones += 1
        record = _scan(name, sha, "tests")
        shutil.rmtree(WORK / _slug(name), ignore_errors=True)
        if record is None:
            entry["skipped"].append({"full_name": name, "reason": "scan_failed"})
            continue
        if candidates.vendors(record["findings"]):
            entry["skipped"].append({"full_name": name, "reason": "vendors_the_sdk"})
            continue
        if not any(row["kind"] in ACTIONABLE_KINDS for row in record["findings"]):
            entry["skipped"].append({"full_name": name, "reason": "no_finding"})
            continue
        row = candidates_collect._row(repository, sha, "tests")
        if "test_files" not in row["tests"]:
            entry["skipped"].append({"full_name": name, "reason": "no_test_file"})
            continue
        entry["outcome"] = "drawn"
        entry["drawn"].append(name)
        owners[row["owner"]] = owners.get(row["owner"], 0) + 1
        taken.add(name)
        rows.append(row)
        records.append(record)
        print(f"  tests: drew {name}", flush=True)
    print(f"  tests: {entry['outcome']} after {entry['examined']} result(s)", flush=True)
    return entry, [rows, records]


def draw_control(
    control: Control, taken: set[str], owners: dict[str, int]
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    hits, names = candidates_collect._search(control.query)
    entry: dict[str, Any] = {
        "control": control.id,
        "shape": control.shape,
        "query": control.query,
        "hits": hits,
        "examined": 0,
        "outcome": "absent" if hits == 0 else "no_eligible_result",
        "drawn": None,
        "witness": None,
        "skipped": [],
    }
    clones = 0
    for name in names[: candidates_collect.EXAMINE_CAP]:
        entry["examined"] += 1
        repository = _eligible(name, taken, owners, entry)
        if repository is None:
            continue
        if clones >= candidates_collect.CLONE_CAP:
            entry["skipped"].append({"full_name": name, "reason": "clone_budget_spent"})
            continue
        sha = _head(name, repository)
        if sha is None:
            entry["skipped"].append({"full_name": name, "reason": "gone"})
            continue
        clones += 1
        record = _scan(name, sha, control.id)
        checkout = WORK / _slug(name)
        witness = _witness(checkout, control.witness, control.where)
        shutil.rmtree(checkout, ignore_errors=True)
        if record is None:
            entry["skipped"].append({"full_name": name, "reason": "scan_failed"})
            continue
        if any(row["kind"] in cases.CONTROL_KINDS for row in record["findings"]):
            entry["skipped"].append({"full_name": name, "reason": "not_a_control"})
            continue
        if witness is None:
            entry["skipped"].append({"full_name": name, "reason": "no_witness"})
            continue
        entry["outcome"] = "drawn"
        entry["drawn"] = name
        entry["witness"] = witness
        owners[repository["owner"]["login"]] = owners.get(repository["owner"]["login"], 0) + 1
        taken.add(name)
        print(f"  {control.id}: drew {name} ({witness})", flush=True)
        return entry, candidates_collect._row(repository, sha, f"control:{control.id}"), record
    print(f"  {control.id}: {entry['outcome']} after {entry['examined']} result(s)", flush=True)
    return entry, None, None


def draw() -> None:
    corpus = yaml.safe_load(candidates.DATA.read_text(encoding="utf-8"))
    taken = {row["full_name"] for row in corpus["candidates"]}
    owners: dict[str, int] = {}
    for row in corpus["candidates"]:
        owners[row["owner"]] = owners.get(row["owner"], 0) + 1

    tests_entry, (rows, records) = draw_test_suites(taken, owners)
    controls: list[dict[str, Any]] = []
    for control in CONTROLS:
        entry, row, record = draw_control(control, taken, owners)
        controls.append(entry)
        if row is not None and record is not None:
            rows.append(row)
            records.append(record)

    RESULTS.mkdir(parents=True, exist_ok=True)
    RESULTS.joinpath("scan.json").write_text(
        json.dumps({**gate1_collect._provenance(), "scanned": records}, indent=2) + "\n",
        encoding="utf-8",
    )
    document = {
        "drawn_at": candidates_collect._now(),
        "corpus": "bench/candidates.yaml",
        "scan": "bench/results/cases/scan.json",
        "examine_cap": candidates_collect.EXAMINE_CAP,
        "clone_cap": candidates_collect.CLONE_CAP,
        "tests_clone_cap": TESTS_CLONE_CAP,
        "test_suites": tests_entry,
        "controls": controls,
        "drawn": rows,
    }
    DATA.write_text(yaml.safe_dump(document, sort_keys=False, width=100), encoding="utf-8")
    print(f"wrote {DATA} with {len(rows)} repositories", flush=True)


def checkout(full_name: str) -> int:
    known = cases.repositories()
    if full_name not in known:
        print(f"{full_name} is neither a candidate nor drawn for T27", flush=True)
        return 1
    into = WORK / _slug(full_name)
    _fetch(full_name, known[full_name]["sha"], into)
    print(into, flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("draw", help="run both dated draws and write bench/cases_draws.yaml")
    one = sub.add_parser("checkout", help="materialise one repository for a reviewer to read")
    one.add_argument("full_name")
    arguments = parser.parse_args(argv)
    if arguments.command == "checkout":
        return checkout(arguments.full_name)
    draw()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
