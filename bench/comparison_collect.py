"""Prepare the comparison arm's checkouts and record what the arm left behind.

Each case is fetched once and copied, so the arm's tree and its baseline are the same bytes.
The record holds only paths, lines, kinds, symbols and counts: repository code is never vendored.
The arm is blind by digest-named trees and one fixed prompt, not by sandbox (ADR-045 D2).

Usage::

    python bench/comparison_collect.py prepare --work /tmp/obelize-comparison
    #   ... run the agent over each tree the work order names ...
    python bench/comparison_collect.py record --work /tmp/obelize-comparison

Not run in CI: `prepare` needs the network and `record` needs the trees on disk.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shlex
import shutil
import sys
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cases
import run
from run import Execute

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "bench" / "results" / "comparison"
PROMPT = ROOT / "bench" / "COMPARISON_PROMPT.md"

# Bump when a field changes meaning; never reuse a number.
SCHEMA_VERSION = 1

# The guide the benchmark protocol names.
GUIDE_URL = "https://ai.google.dev/gemini-api/docs/migrate"

GUIDE_TIMEOUT_S = 120
FETCH_TIMEOUT_S = run.FETCH_TIMEOUT_S
VENV_TIMEOUT_S = run.VENV_TIMEOUT_S
INSTALL_TIMEOUT_S = run.INSTALL_TIMEOUT_S
COMPILE_TIMEOUT_S = run.COMPILE_TIMEOUT_S
SCAN_TIMEOUT_S = 600
TEST_TIMEOUT_S = run.TEST_TIMEOUT_S
GIT_TIMEOUT_S = 120

# Written to each clone's `.git/info/exclude` before staging, so these never count as edits.
NOISE: tuple[str, ...] = (
    ".venv/",
    "venv/",
    ".obelize/",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    "node_modules/",
    ".DS_Store",
)

# Block tags become newlines; other tags vanish without a space, which keeps `<pre>` spacing.
BLOCKS = re.compile(
    r"(?i)</?(?:p|div|br|h[1-6]|li|ul|ol|tr|table|section|article|pre|header"
    r"|footer|nav|aside|main|dl|dt|dd|blockquote|hr|title)\b[^>]*>"
)
SCRIPTS = re.compile(r"(?is)<(script|style|template)[^>]*>.*?</\1>")
TAGS = re.compile(r"(?s)<[^>]+>")
BLANKS = re.compile(r"\n{3,}")

# The prompt file's leading comment, which names this repository and is never shown to the arm.
NOTE = re.compile(r"(?s)\A<!--.*?-->")

# Injected network access; `record` needs none.
Fetch = Callable[[str], bytes]


def slug(case_id: str) -> str:
    """A case's directory name: a digest of its id, so the agent cannot look the repo up."""
    return hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:8]


def rendered(tree: Path, guide: Path, meta: Path) -> str:
    """The fixed prompt with this case's three paths; a copy that differs is refused on read."""
    text = NOTE.sub("", PROMPT.read_text(encoding="utf-8"), count=1).lstrip()
    for token, value in (("{{TREE}}", tree), ("{{GUIDE}}", guide), ("{{META}}", meta)):
        if token not in text:
            raise SystemExit(f"{PROMPT.name} has no {token} to substitute")
        text = text.replace(token, str(value))
    return text


def dev_cases() -> list[run.Case]:
    """The development split only: running the arm on the holdout would spend it."""
    found = [case for case in run.corpus() if case.split == "dev"]
    if not found:
        raise SystemExit("no development-split cases; bench/cases.yaml has no dev split")
    return found


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=GUIDE_TIMEOUT_S) as response:  # noqa: S310
        raw: bytes = response.read()
    return raw


def as_text(raw: bytes) -> str:
    """The guide as text, by a rerunnable rule; this is what the arm reads."""
    page = raw.decode("utf-8", "replace")
    page = SCRIPTS.sub(" ", page)
    page = BLOCKS.sub("\n", page)
    page = html.unescape(TAGS.sub("", page))
    lines = [line.rstrip() for line in page.split("\n")]
    return BLANKS.sub("\n\n", "\n".join(lines)).strip() + "\n"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def guide(work: Path, fetch: Fetch, at: str) -> dict[str, Any]:
    """Snapshot the guide once for all cases (ADR-045 D5); third-party bytes, never committed."""
    raw = fetch(GUIDE_URL)
    if not raw:
        raise SystemExit(f"{GUIDE_URL} returned nothing; the arm has no guide to read")
    text = as_text(raw)
    folder = work / "guide"
    folder.mkdir(parents=True)
    (folder / "guide.html").write_bytes(raw)
    (folder / "guide.txt").write_text(text, encoding="utf-8")
    snapshot = {
        "url": GUIDE_URL,
        "fetched_at": at,
        "sha256_html": digest(raw),
        "sha256_text": digest(text.encode("utf-8")),
        "bytes_html": len(raw),
        "bytes_text": len(text.encode("utf-8")),
    }
    (folder / "guide.json").write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    return snapshot


def _empty(work: Path) -> None:
    """Refuse a non-empty root, whose old edits would be graded as new, or an unisolated one."""
    if work.exists() and any(work.iterdir()):
        raise SystemExit(f"{work} is not empty; the arm fetches into an empty root")
    found = run.unisolated(work)
    if found:
        raise SystemExit(f"{work} is not isolated: {'; '.join(found)}")


def _fetch_case(case: run.Case, into: Path, *, execute: Execute, env: Mapping[str, str]) -> None:
    """One case at its pinned commit, by the round's own fetch commands."""
    into.mkdir(parents=True)
    assert case.repo is not None  # noqa: S101 - a corpus case always has one
    assert case.sha is not None  # noqa: S101
    for argv in run.fetch_argv(into, case.repo, case.sha):
        completed = execute(argv, into, env, FETCH_TIMEOUT_S)
        if completed.exit_code != 0:
            raise SystemExit(f"{case.id}: {argv[3]} failed ({completed.exit_code})")
    _exclude(into)


def _exclude(tree: Path) -> None:
    (tree / ".git" / "info" / "exclude").write_text("\n".join(NOISE) + "\n", encoding="utf-8")


def prepare(
    work: Path, *, execute: Execute, fetch: Fetch, env: Mapping[str, str], at: str
) -> dict[str, Any]:
    """Materialise the arm: one guide, and two identical trees per case."""
    _empty(work)
    work.mkdir(parents=True, exist_ok=True)
    snapshot = guide(work, fetch, at)
    order: dict[str, Any] = {}
    for case in dev_cases():
        name = slug(case.id)
        tree = work / "agent" / name
        _fetch_case(case, tree, execute=execute, env=env)
        shutil.copytree(tree, work / "base" / name)
        meta = work / "meta" / name
        meta.mkdir(parents=True)
        (meta / "prompt.md").write_text(
            rendered(tree, work / "guide" / "guide.txt", meta), encoding="utf-8"
        )
        order[name] = {"case": case.id, "tree": str(tree), "meta": str(meta)}
    document = {"guide": snapshot, "order": order, "prepared_at": at}
    (work / "order.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return document


def _git(
    tree: Path, argv: Sequence[str], *, execute: Execute, env: Mapping[str, str], what: str
) -> str:
    completed = execute(("git", "-C", str(tree), *argv), tree, env, GIT_TIMEOUT_S)
    if completed.exit_code != 0:
        raise SystemExit(f"{tree.name}: {what} failed ({completed.exit_code})")
    return completed.output


def head(tree: Path, *, execute: Execute, env: Mapping[str, str]) -> str:
    """The tree's commit; callers require the pin, or `git diff HEAD` misses committed work."""
    return _git(tree, ("rev-parse", "HEAD"), execute=execute, env=env, what="rev-parse").strip()


def changes(tree: Path, *, execute: Execute, env: Mapping[str, str]) -> list[dict[str, Any]]:
    """Every path the arm touched, with line counts; staged first so new files count.

    Renames are off: a delete plus an add is what the key rows see.
    """
    _git(tree, ("add", "-A"), execute=execute, env=env, what="add")
    numbers = _git(
        tree,
        ("diff", "--cached", "--no-renames", "--numstat", "-z", "HEAD"),
        execute=execute,
        env=env,
        what="numstat",
    )
    states = _git(
        tree,
        ("diff", "--cached", "--no-renames", "--name-status", "-z", "HEAD"),
        execute=execute,
        env=env,
        what="name-status",
    )
    counted = dict(_numstat(numbers))
    found = []
    for status, path in _pairs(states):
        added, removed = counted.get(path, (None, None))
        found.append({"path": path, "status": status, "added": added, "removed": removed})
    return sorted(found, key=lambda change: str(change["path"]))


def _numstat(raw: str) -> list[tuple[str, tuple[int | None, int | None]]]:
    """`added removed path` records, where a binary file's counts are nulls."""
    found = []
    for record in raw.split("\0"):
        if not record:
            continue
        added, removed, path = record.split("\t", 2)
        found.append((path, (_count(added), _count(removed))))
    return found


def _count(field: str) -> int | None:
    return None if field == "-" else int(field)


def _pairs(raw: str) -> list[tuple[str, str]]:
    """`status`, `path` pairs out of a NUL-separated `--name-status`."""
    fields = [field for field in raw.split("\0") if field]
    return list(zip(fields[0::2], fields[1::2], strict=True))


def timings(meta: Path) -> tuple[int, int]:
    """The agent's own start/finish stamps; missing (not run) or backwards (run twice) fails."""
    found = {}
    for name in ("started", "finished"):
        path = meta / name
        if not path.is_file():
            raise SystemExit(f"{meta.name}: no {name} stamp; the arm did not run this case")
        found[name] = int(path.read_text(encoding="utf-8").strip())
    if found["finished"] < found["started"]:
        raise SystemExit(f"{meta.name}: finished {found['finished']} is before its start")
    return found["started"], found["finished"]


def scan_argv(tree: Path) -> tuple[str, ...]:
    """No `--json`: the run folder's identical copy cannot be truncated by the output cap."""
    return (
        sys.executable,
        "-m",
        "obelize.cli",
        "scan",
        "--repo",
        str(tree),
        "--pack",
        run.DEFAULT_PACK,
    )


def findings(tree: Path, *, execute: Execute, env: Mapping[str, str]) -> list[list[Any]]:
    """Every finding a scan of this tree reports, as `[path, line, kind, symbol]`."""
    completed = execute(scan_argv(tree), tree, env, SCAN_TIMEOUT_S)
    if completed.exit_code != 0:
        raise SystemExit(f"{tree.name}: scan exited {completed.exit_code}")
    folders = sorted(path for path in (tree / ".obelize" / "runs").glob("*") if path.is_dir())
    if len(folders) != 1:
        raise SystemExit(f"{tree.name}: expected one run folder, found {len(folders)}")
    document = json.loads((folders[0] / "findings.json").read_text(encoding="utf-8"))
    shutil.rmtree(tree / ".obelize")
    return [
        [str(row["path"]), int(row["line"]), str(row["kind"]), str(row.get("symbol") or "")]
        for row in document["findings"]
    ]


def missing_key_files(case: run.Case, tree: Path) -> list[str]:
    """Key files missing from the arm's tree: a deleted file would otherwise read as migrated."""
    named = {path for path, _, _ in run.expected_rows(case)}
    return sorted(path for path in named if not (tree / path).exists())


def _venv(into: Path, case: run.Case, *, execute: Execute, env: Mapping[str, str]) -> Path:
    """The case's pinned interpreter, as a full uv key: another Python compiles another grammar."""
    assert case.python is not None  # noqa: S101 - a corpus case always pins one
    if not into.exists():
        into.parent.mkdir(parents=True, exist_ok=True)
        completed = execute(run.venv_argv(into, case.python), into.parent, env, VENV_TIMEOUT_S)
        if completed.exit_code != 0:
            raise SystemExit(f"{case.id}: uv venv exited {completed.exit_code}")
    return into / "bin" / "python"


def _cased(env: Mapping[str, str], venv: Path) -> dict[str, str]:
    """`env` with this case's venv activated."""
    return {
        **env,
        "VIRTUAL_ENV": str(venv),
        "PATH": f"{venv / 'bin'}{os.pathsep}{env.get('PATH', '')}",
    }


def written(changed: Sequence[Mapping[str, Any]]) -> list[str]:
    """The `.py` files the arm wrote, minus deletions: the set the round compiles for obelize."""
    return sorted(
        str(change["path"])
        for change in changed
        if change["status"] != "D" and str(change["path"]).endswith(".py")
    )


def compiles(
    tree: Path, paths: Sequence[str], interpreter: Path, *, execute: Execute, env: Mapping[str, str]
) -> bool | None:
    """Whether everything the arm wrote still compiles, or `None` if it wrote none."""
    if not paths:
        return None
    completed = execute(run.compile_argv(interpreter, paths), tree, env, COMPILE_TIMEOUT_S)
    return completed.exit_code == 0


def suite(
    case: run.Case,
    tree: Path,
    interpreter: Path,
    junit: Path,
    *,
    execute: Execute,
    env: Mapping[str, str],
) -> dict[str, Any]:
    """The case's own tests on the arm's tree under the new SDK; the baseline is the round's."""
    assert case.test_cmd is not None  # noqa: S101 - the caller checks
    for command in case.install:
        installed = execute(shlex.split(command), tree, env, INSTALL_TIMEOUT_S)
        if installed.exit_code != 0:
            raise SystemExit(f"{case.id}: install `{command}` exited {installed.exit_code}")
    pinned = execute(
        run.pin_argv(interpreter, run.TO_DISTRIBUTION, case.to_version or ""),
        tree,
        env,
        INSTALL_TIMEOUT_S,
    )
    if pinned.exit_code != 0:
        raise SystemExit(f"{case.id}: pinning {run.TO_DISTRIBUTION} exited {pinned.exit_code}")
    probe = execute(run.probe_argv(interpreter, run.TO_DISTRIBUTION), tree, env, VENV_TIMEOUT_S)
    seen = run.observed_version(probe)
    wrong = run.mismatch(run.TO_DISTRIBUTION, case.to_version or "", seen)
    if wrong is not None:
        raise SystemExit(f"{case.id}: {wrong}")
    junit.parent.mkdir(parents=True, exist_ok=True)
    completed = execute(
        run.suite_argv(case.test_cmd, junit, interpreter), tree, env, TEST_TIMEOUT_S
    )
    passed, failed, skipped = run.junit_counts(junit)
    return {
        "status": run.suite_status(completed, failed),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "sdk_to": seen,
    }


def _obelize_tree(work: Path, name: str, source: Path) -> Path:
    """A copy of the round's obelize tree minus `.obelize` and `.venv`; never the original."""
    if not source.is_dir():
        raise SystemExit(f"{source}: the round's work tree is gone; the arms cannot be compared")
    destination = work / "obelize" / name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".obelize", ".venv"))
    _exclude(destination)
    return destination


def repeat(work: Path, wanted: Sequence[str]) -> list[str]:
    """Stage a second agent run of the named cases from the untouched `base/` copies."""
    known = {case.id: slug(case.id) for case in dev_cases()}
    staged = []
    for case_id in wanted:
        if case_id not in known:
            raise SystemExit(f"{case_id}: not a development-split case")
        name = known[case_id]
        source = work / "base" / name
        if not source.is_dir():
            raise SystemExit(f"{source}: nothing prepared for {case_id}")
        tree = work / "repeat" / name
        if tree.exists():
            raise SystemExit(f"{tree}: already staged; a third run needs its own root")
        shutil.copytree(source, tree)
        meta = work / "repeat-meta" / name
        meta.mkdir(parents=True)
        (meta / "prompt.md").write_text(
            rendered(tree, work / "guide" / "guide.txt", meta), encoding="utf-8"
        )
        staged.append(name)
    return staged


def _repeat_record(
    case: run.Case, work: Path, name: str, *, execute: Execute, env: Mapping[str, str]
) -> dict[str, Any] | None:
    """The second run of one case, when there was one."""
    tree = work / "repeat" / name
    if not tree.is_dir():
        return None
    meta = work / "repeat-meta" / name
    if (meta / "prompt.md").read_text(encoding="utf-8") != rendered(
        tree, work / "guide" / "guide.txt", meta
    ):
        raise SystemExit(f"{case.id}: the repeat's prompt is not {PROMPT.name}")
    started, finished = timings(meta)
    changed = changes(tree, execute=execute, env=env)
    return {
        "started_at": started,
        "finished_at": finished,
        "runtime_seconds": finished - started,
        "changes": changed,
        "findings": findings(tree, execute=execute, env=env),
    }


def _order(work: Path) -> dict[str, Any]:
    """The work order `prepare` wrote; a guide whose bytes changed since is refused."""
    path = work / "order.json"
    if not path.is_file():
        raise SystemExit(f"{path}: nothing prepared here; run `prepare` first")
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    snapshot = document["guide"]
    for name, field in (("guide.html", "sha256_html"), ("guide.txt", "sha256_text")):
        seen = digest((work / "guide" / name).read_bytes())
        if seen != snapshot[field]:
            raise SystemExit(f"{name} is {seen}, prepared as {snapshot[field]}")
    return document


def _case_record(
    case: run.Case, work: Path, number: int, *, execute: Execute, env: Mapping[str, str]
) -> dict[str, Any]:
    """Everything the record holds about one case, from the three trees it has."""
    name = slug(case.id)
    agent, base = work / "agent" / name, work / "base" / name
    for tree in (agent, base):
        if not tree.is_dir():
            raise SystemExit(f"{tree}: not prepared; the arm has no tree for {case.id}")
        seen = head(tree, execute=execute, env=env)
        if seen != case.sha:
            raise SystemExit(f"{case.id}: {tree.name} is at {seen}, pinned {case.sha}")
    meta = work / "meta" / name
    handed = (meta / "prompt.md").read_text(encoding="utf-8")
    if handed != rendered(agent, work / "guide" / "guide.txt", meta):
        raise SystemExit(f"{case.id}: the prompt it was given is not {PROMPT.name}")
    started, finished = timings(meta)
    changed = changes(agent, execute=execute, env=env)
    interpreter = _venv(work / "venv" / name, case, execute=execute, env=env)
    cased = _cased(env, work / "venv" / name)
    obelize = _obelize_tree(work, name, run.WORK / f"round-{number}" / case.id)
    if head(obelize, execute=execute, env=env) != case.sha:
        raise SystemExit(f"{case.id}: the round's checkout is not at {case.sha}")
    return {
        "slug": name,
        "started_at": started,
        "finished_at": finished,
        "runtime_seconds": finished - started,
        "changes": changed,
        "obelize_changes": changes(obelize, execute=execute, env=env),
        "written": written(changed),
        "compiles": compiles(agent, written(changed), interpreter, execute=execute, env=cased),
        "missing_key_files": missing_key_files(case, agent),
        "findings": {
            "base": findings(base, execute=execute, env=env),
            "general_agent": findings(agent, execute=execute, env=env),
            "obelize": findings(obelize, execute=execute, env=env),
        },
        "repeat": _repeat_record(case, work, name, execute=execute, env=env),
        "tests_after": (
            None
            if case.test_cmd is None
            else suite(
                case,
                agent,
                interpreter,
                work / "junit" / f"{name}.xml",
                execute=execute,
                env=cased,
            )
        ),
    }


def record(work: Path, number: int, *, execute: Execute, env: Mapping[str, str]) -> dict[str, Any]:
    """Read the arm back off disk into the one file the scorer reads."""
    document = _order(work)
    collected = {
        case.id: _case_record(case, work, number, execute=execute, env=env) for case in dev_cases()
    }
    return {
        "arms": ["general_agent", "obelize"],
        "cases": collected,
        "guide": document["guide"],
        "prepared_at": document["prepared_at"],
        "round": number,
        "schema_version": SCHEMA_VERSION,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare or read back the comparison arm.")
    parser.add_argument("action", choices=("prepare", "repeat", "record"))
    parser.add_argument("--work", type=Path, required=True, help="the arm's work root")
    parser.add_argument(
        "--round", type=int, default=None, help="round number (default: the case file's)"
    )
    parser.add_argument("--at", default=None, help="the timestamp `prepare` records")
    parser.add_argument("--case", action="append", default=[], help="a case `repeat` stages")
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    number = arguments.round if arguments.round is not None else int(cases.load().cases["round"])
    env = dict(os.environ)
    if arguments.action == "prepare":
        at = arguments.at or _now()
        document = prepare(arguments.work, execute=run.shell, fetch=download, env=env, at=at)
        print(f"{arguments.work}: {len(document['order'])} cases prepared, guide {at}")
        return 0
    if arguments.action == "repeat":
        staged = repeat(arguments.work, arguments.case)
        print(f"{arguments.work}: {len(staged)} cases staged for a second run")
        return 0
    document = record(arguments.work, number, execute=run.shell, env=env)
    RESULTS.mkdir(parents=True, exist_ok=True)
    destination = RESULTS / f"round-{number}.json"
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    edits = sum(len(case["changes"]) for case in document["cases"].values())
    print(f"{destination.name}: {len(document['cases'])} cases, {edits} changed files")
    return 0


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":  # pragma: no cover - run by hand, twice per round
    sys.exit(main())
