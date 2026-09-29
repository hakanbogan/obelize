"""Byte-identical scans across `--jobs`, hash seeds, a shuffled walk and two merged roots.

libcst returns references as an identity-hashed `set`, so order follows the heap and varies only
between fresh processes. A path is unique only within one root, so `runner.sort_key` adds the hash.
"""

from __future__ import annotations

import dataclasses
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import harness
import pytest

from obelize.models import Config
from obelize.scan import runner, walker

# Twelve candidates, four bails and two multi-reference bindings: the shape set order would break.
SUBJECT = "escapes"

# Oversubscribing CI's cores must not change the answer either.
JOBS = 8

CASE_NAMES = sorted(harness.CASES)

# One scan in a fresh interpreter. `-c` leaves `spawn` no `__main__` path to re-run, so the
# children import the installed `obelize.scan.runner` by name.
DRIVER = """
import json, sys
sys.path.insert(0, sys.argv[1])
import harness
from obelize.scan import runner

root, config, spec = harness.configured(sys.argv[2])
pooled = runner.scan(root, config, spec, jobs=int(sys.argv[3]))
print(json.dumps({
    "serial": harness.digest(runner.scan(root, config, spec, jobs=1)),
    "pooled": harness.digest(pooled),
    "workers": pooled.workers,
}))
"""

# Two roots put different contents at this path: the collision measured over real roots.
COLLIDING = "tests/__init__.py"
FIRST = 'import google.generativeai as genai\n\ngenai.configure(api_key="first")\n'
SECOND = 'import google.generativeai as genai\n\ngenai.configure(api_key="second")\n'


def driver(name: str, cwd: Path, seed: str | None) -> dict[str, object]:
    environment = dict(os.environ)
    environment.pop("PYTHONHASHSEED", None)
    if seed is not None:
        environment["PYTHONHASHSEED"] = seed
    completed = subprocess.run(
        [sys.executable, "-c", DRIVER, str(Path(harness.__file__).parent), name, str(JOBS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=cwd,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    loaded = json.loads(completed.stdout)
    assert isinstance(loaded, dict)
    return loaded


def corpus(root: Path, body: str) -> Path:
    """One legacy file at the path both roots share."""
    (root / COLLIDING).parent.mkdir(parents=True, exist_ok=True)
    (root / COLLIDING).write_text(body, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def expected() -> str:
    """The subject's digest from this interpreter."""
    root, config, spec = harness.configured(SUBJECT)
    return harness.digest(runner.scan(root, config, spec, jobs=1))


@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_pool_and_one_process_produce_the_same_scan(name: str) -> None:
    """The digest covers everything a report is written from; every case is below the crossover,
    so the pool runs only because a typed `--jobs` is taken as typed."""
    root, config, spec = harness.configured(name)
    serial = runner.scan(root, config, spec, jobs=1)
    pooled = runner.scan(root, config, spec, jobs=JOBS)
    assert serial.workers == 1
    assert pooled.workers == JOBS
    assert harness.digest(pooled) == harness.digest(serial)
    assert pooled.results == serial.results


@pytest.mark.parametrize("seed", ["0", "1", None], ids=["seed-0", "seed-1", "seed-unset"])
def test_the_answer_does_not_depend_on_the_hash_seed(seed: str | None, expected: str) -> None:
    """In-process scans share heap layout, so each seed gets a fresh process; unset is a user's."""
    result = driver(SUBJECT, cwd=harness.ROOT, seed=seed)
    assert result["serial"] == expected
    assert result["pooled"] == expected
    assert result["workers"] == JOBS


def test_the_pool_runs_outside_the_repository_that_contains_it(
    tmp_path: Path, expected: str
) -> None:
    """`spawn` imports the worker by module name, so obelize must be installed, not merely found
    through `sys.path[0]` in its checkout (else `BrokenProcessPool`)."""
    result = driver(SUBJECT, cwd=tmp_path, seed=None)
    assert result["pooled"] == expected


def test_a_shuffled_selection_does_not_change_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The runner may not rely on the walker's sort; manifests are shuffled too, since their pass
    merges rows from several files into one document order."""
    root, config, spec = harness.configured("manifests")
    truth = runner.scan(root, config, spec)
    selected = walker.walk

    def shuffled(root: Path, config: Config) -> walker.Walk:
        result = selected(root, config)
        # S311: a seeded shuffle of a file list; no key is chosen.
        shuffler = random.Random(0)  # noqa: S311
        files, manifests = list(result.files), list(result.manifests)
        shuffler.shuffle(files)
        shuffler.shuffle(manifests)
        return dataclasses.replace(result, files=tuple(files), manifests=tuple(manifests))

    monkeypatch.setattr(walker, "walk", shuffled)
    assert harness.digest(runner.scan(root, config, spec)) == harness.digest(truth)


def test_two_roots_that_share_a_relative_path_are_still_totally_ordered(tmp_path: Path) -> None:
    """Checked against the content hashes, not `sort_key`'s output, which would grade itself."""
    spec = harness.spec()
    config = Config()
    first = runner.scan(corpus(tmp_path / "a", FIRST), config, spec)
    second = runner.scan(corpus(tmp_path / "b", SECOND), config, spec)
    assert [result.path for result in first.results] == [COLLIDING]
    assert first.results[0].sha256 != second.results[0].sha256

    forwards = runner.ordered([*first.results, *second.results])
    backwards = runner.ordered([*second.results, *first.results])
    assert forwards == backwards
    assert [result.sha256 for result in forwards] == sorted(
        [first.results[0].sha256, second.results[0].sha256]
    )


def test_the_path_alone_is_not_a_total_order(tmp_path: Path) -> None:
    """Without the hash the two compare equal, and stable `sorted` keeps the caller's walk order."""
    spec = harness.spec()
    config = Config()
    first = runner.scan(corpus(tmp_path / "a", FIRST), config, spec)
    second = runner.scan(corpus(tmp_path / "b", SECOND), config, spec)

    def by_path(results: list[runner.FileResult]) -> list[str]:
        return [row.sha256 for row in sorted(results, key=lambda row: os.fsencode(row.path))]

    assert by_path([*first.results, *second.results]) != by_path([*second.results, *first.results])


@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_payload_that_crosses_the_pool_boundary_is_plain_data(name: str) -> None:
    """The pool pickles; a JSON trip proves no `cst.Module`, pydantic model or dataclass crosses
    (ADR-005)."""
    root, config, spec = harness.configured(name)
    for result in runner.scan(root, config, spec, jobs=1).results:
        restored = runner.restore(json.loads(json.dumps(runner.payload(result))))
        assert restored == result


@pytest.mark.parametrize("name", CASE_NAMES)
def test_within_one_root_the_findings_follow_the_files(name: str) -> None:
    """A path is unique within one root, so the findings are the per-file plans in key order;
    manifest rows go by kind, not path, as `setup.py` also has a code-pass finding."""
    root, config, spec = harness.configured(name)
    scan = runner.scan(root, config, spec, jobs=1)
    assert [row.sort_key for row in scan.findings] == sorted(row.sort_key for row in scan.findings)
    assert [row for row in scan.findings if row.kind != "manifest"] == [
        row for result in scan.results for row in result.plan.findings
    ]
