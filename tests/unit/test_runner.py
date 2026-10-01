"""`runner.scan` beyond the oracle: files no worker sees, the pool boundary, when to pool."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Any

import pytest
from acme import SPEC

from obelize.config import ConfigError
from obelize.impact import planner
from obelize.models import Config, ImpactPlan, ImpactPolicy
from obelize.native import processes
from obelize.scan import analysis, parse, reach, runner
from platforms import AS_ROOT, deny, posix_only

# Survives the prefilter and yields findings, a binding and a receiver record.
LEGACY = """\
import acme.sdk

acme.sdk.configure(api_key="k")
MODEL = acme.sdk.Model("m")


def ask(question: str) -> str:
    return MODEL.run(question)
"""

# Eliminated by the prefilter, yet still selected, hashed and returned.
PLAIN = """\
def add(left: int, right: int) -> int:
    return left + right
"""

MANIFEST = "acme-sdk==1.0.0\n"

# No client: the constructor call does not resolve, and F-1 withholds the import with it.
NO_CLIENT = """import acme.sdk

MODEL = acme.sdk.Model("m")
"""

# A prose mention: a finding, not an edit.
MENTION = "# acme.sdk was the old import path.\nVALUE = 1\n"

# Refused by the first gate: one finding, one row.
BROKEN = "import acme.sdk\n\ndef f(:\n    pass\n"


def tree(root: Path, files: dict[str, str]) -> Path:
    """Write the files; `tmp_path` is not a git checkout, so the walker's fallback lists them."""
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
    return root


def scanned(
    root: Path,
    config: Config | None = None,
    policy: ImpactPolicy | None = None,
    jobs: int | None = None,
) -> runner.Scan:
    return runner.scan(root, config or Config(), SPEC, policy=policy, jobs=jobs)


def at(scan: runner.Scan, path: str) -> runner.FileResult:
    return next(result for result in scan.results if result.path == path)


def test_every_selected_file_is_a_result_whatever_became_of_it(tmp_path: Path) -> None:
    """Unread and eliminated files count too, or "no findings" hides how many were looked at."""
    root = tree(tmp_path, {"app.py": LEGACY, "plain.py": PLAIN, "big.py": PLAIN * 40})
    scan = scanned(root, Config(max_file_bytes=200))

    assert [result.path for result in scan.results] == ["app.py", "big.py", "plain.py"]
    assert at(scan, "app.py").parsed is True
    assert at(scan, "plain.py").parsed is False
    assert at(scan, "big.py").parsed is False
    assert scan.counts.files_selected == 3
    assert scan.counts.files_parsed == 1


def test_a_file_that_was_never_read_has_no_hash_and_one_row(tmp_path: Path) -> None:
    root = tree(tmp_path, {"big.py": LEGACY * 20})
    scan = scanned(root, Config(max_file_bytes=100))

    result = at(scan, "big.py")
    assert (result.sha256, result.parsed, result.plan.findings) == ("", False, ())
    assert [(row.path, row.code) for row in result.limitations] == [("big.py", "file_too_large")]
    assert scan.limitations == result.limitations


def test_a_file_the_prefilter_eliminated_is_hashed_and_says_nothing(tmp_path: Path) -> None:
    """Unlike a refusal, elimination reads the bytes, so the digest is real."""
    root = tree(tmp_path, {"plain.py": PLAIN})
    result = at(scanned(root), "plain.py")

    assert len(result.sha256) == 64
    assert (result.parsed, result.plan.findings, result.limitations) == (False, (), ())


def test_the_runner_reads_a_file_exactly_as_the_reader_would(tmp_path: Path) -> None:
    """Parent reads and prefilters, worker gates and parses: the halves must equal `parse.read`."""
    files = {"app.py": LEGACY, "plain.py": PLAIN, "big.py": PLAIN * 40}
    root = tree(tmp_path, files)
    config = Config(max_file_bytes=200)

    for name in sorted(files):
        read = parse.read(root, name, SPEC, config)
        expected = planner.plan(analysis.analyse(read, SPEC), SPEC)
        result = at(scanned(root, config), name)
        assert result.plan == expected
        assert result.parsed == (read.status == "parsed")
        assert result.limitations == read.limitations


def test_the_same_refusal_is_reported_once(tmp_path: Path) -> None:
    """`setup.py` is both source and manifest, so two passes refuse it for one reason (ADR-021)."""
    root = tree(tmp_path, {"setup.py": LEGACY * 20})
    scan = scanned(root, Config(max_file_bytes=100))

    assert [(row.path, row.code) for row in scan.limitations] == [("setup.py", "file_too_large")]


def test_a_manifest_whose_python_floor_does_not_parse_is_a_limitation(tmp_path: Path) -> None:
    root = tree(tmp_path, {"pyproject.toml": 'urls = { a = "x", }\n', "app.py": LEGACY})
    scan = scanned(root)
    assert scan.runtime is None
    assert [(row.path, row.code) for row in scan.limitations] == [
        ("pyproject.toml", "input_does_not_parse")
    ]


def test_the_manifest_pass_reduces_over_the_files(tmp_path: Path) -> None:
    """F-2's two edits, from a repository where exactly one file migrates."""
    root = tree(tmp_path, {"app.py": LEGACY, "requirements.txt": MANIFEST})
    scan = scanned(root)

    assert [
        (row.path, row.line, row.symbol, row.scan_status) for row in scan.manifests.findings
    ] == [("requirements.txt", 1, "acme-sdk", "eligible")]
    assert scan.manifests.blocking == ()
    assert [row.kind for row in scan.findings if row.kind == "manifest"] == ["manifest"]


def test_the_counts_are_the_four_statuses_and_not_four_copies_of_one(tmp_path: Path) -> None:
    """Distinct counts expose a transposition (`ScanCounts` checks only the sum): four resolved
    usages, an import and call F-1 withholds together, one prose mention, one first-gate refusal."""
    root = tree(
        tmp_path,
        {"clean.py": LEGACY, "no_client.py": NO_CLIENT, "mention.py": MENTION, "broken.py": BROKEN},
    )
    counts = scanned(root).counts

    assert counts.model_dump() == {
        "files_selected": 4,
        "files_parsed": 3,
        "findings": 8,
        "eligible": 4,
        "needs_review": 2,
        "unsupported": 1,
        "not_a_usage": 1,
    }


def test_the_findings_are_in_document_order_across_the_whole_repository(tmp_path: Path) -> None:
    """`Pipfile` sorts first but its pass runs last, and `FindingsDocument` refuses unsorted rows,
    so the scan must sort, not concatenate."""
    root = tree(tmp_path, {"zz_app.py": LEGACY, "Pipfile": f"[packages]\n{MANIFEST}"})
    findings = scanned(root).findings

    assert [row.sort_key for row in findings] == sorted(row.sort_key for row in findings)
    assert findings[0].path == "Pipfile"


def test_the_refusals_are_sorted_and_not_in_the_order_the_passes_ran(tmp_path: Path) -> None:
    root = tree(tmp_path, {"zz_app.py": LEGACY * 20, "Pipfile": MANIFEST * 40})
    scan = scanned(root, Config(max_file_bytes=100))

    assert [row.path for row in scan.limitations] == ["Pipfile", "zz_app.py"]


def test_the_receivers_are_paired_with_the_file_they_came_from(tmp_path: Path) -> None:
    """A `Binding` does not carry `escape_lines`; the record behind it does."""
    root = tree(tmp_path, {"pkg/app.py": LEGACY})
    scan = scanned(root)

    assert [(path, receiver.kind, receiver.name) for path, receiver in scan.receivers] == [
        ("pkg/app.py", "module_const", "MODEL")
    ]


@pytest.mark.parametrize("jobs", [1, 2], ids=["in-process", "pooled"])
def test_the_policy_reaches_every_plan(tmp_path: Path, jobs: int) -> None:
    """Pooled too: the worker `initializer` rebuilds the policy, and losing it plans the default."""
    root = tree(tmp_path, {"app.py": LEGACY, "plain.py": PLAIN})
    scan = scanned(root, policy=ImpactPolicy(import_policy="dual"), jobs=jobs)

    assert {result.plan.import_policy for result in scan.results} == {"dual"}


@pytest.mark.parametrize(
    ("cores", "expected"),
    [(None, 1), (1, 1), (2, 1), (3, 2), (8, 7), (64, runner.MAX_WORKERS)],
)
def test_the_default_leaves_a_core_for_the_parent(
    monkeypatch: pytest.MonkeyPatch, cores: int | None, expected: int
) -> None:
    """`os.cpu_count()` may be `None`; on two cores (the measured machine) reserving one leaves
    the in-process path, which is right (ADR-022)."""
    monkeypatch.setattr(os, "cpu_count", lambda: cores)

    assert runner.worker_count(None) == expected


def test_the_default_on_this_machine_is_at_least_one_process() -> None:
    assert runner.worker_count(None) >= 1


def test_a_number_that_was_typed_is_returned_as_typed() -> None:
    """Even above the core count: it is the caller's machine."""
    assert runner.worker_count(3) == 3


@posix_only("Windows' process pool takes at most 61 workers; the stubbed limit below shows it")
def test_posix_puts_no_limit_on_a_typed_number() -> None:
    assert runner.worker_count(1024) == 1024


def test_a_number_above_the_pool_limit_is_refused_and_the_limit_itself_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows' limit, stubbed small: its `ProcessPoolExecutor` raises a `ValueError` above it."""
    monkeypatch.setattr(processes, "WORKER_LIMIT", 2)
    assert runner.worker_count(2) == 2
    with pytest.raises(ConfigError, match="at most 2"):
        runner.worker_count(3)


@pytest.mark.parametrize("jobs", [0, -1])
def test_a_run_with_fewer_than_one_process_is_refused(jobs: int) -> None:
    with pytest.raises(ConfigError, match="must be at least 1"):
        runner.worker_count(jobs)


def test_one_job_is_the_in_process_path(tmp_path: Path) -> None:
    root = tree(tmp_path, {"app.py": LEGACY})
    assert scanned(root, jobs=1).workers == 1


def test_a_number_that_was_typed_is_taken_as_typed(tmp_path: Path) -> None:
    """Two files is far below the crossover, but the threshold only guards the default."""
    root = tree(tmp_path, {"app.py": LEGACY, "other.py": LEGACY})
    pooled = scanned(root, jobs=2)

    assert pooled.workers == 2
    assert pooled.results == scanned(root, jobs=1).results


@pytest.mark.parametrize("delta", [-1, 0], ids=["below", "at"])
def test_the_default_starts_processes_only_at_the_crossover(tmp_path: Path, delta: int) -> None:
    """Under three cores both answers are one worker, by design (ADR-022 D5)."""
    count = runner.POOL_THRESHOLD + delta
    root = tree(tmp_path, {f"module_{index:04d}.py": LEGACY for index in range(count)})
    scan = scanned(root)

    assert scan.counts.files_selected == count
    assert scan.workers == (1 if delta < 0 else runner.worker_count(None))


def test_the_boundary_carries_nothing_but_plain_data(tmp_path: Path) -> None:
    """The pool pickles; a JSON trip proves plain data: a `cst.Module` fails to serialise, and a
    tuple back as a list breaks `Receiver` equality."""
    root = tree(tmp_path, {"app.py": LEGACY, "plain.py": PLAIN})
    for result in scanned(root).results:
        row = runner.payload(result)
        assert sorted(row) == ["limitations", "parsed", "path", "plan", "receivers", "sha256"]
        assert runner.restore(json.loads(json.dumps(row))) == result


def test_the_worker_produces_what_the_parent_would_have(tmp_path: Path) -> None:
    """In-process, since pool children go unmeasured; `test_scan_determinism.py` covers the pool."""
    root = tree(tmp_path, {"app.py": LEGACY})
    data = (root / "app.py").read_bytes()
    candidate = runner.Candidate(path="app.py", sha256="0" * 64, data=data)

    runner._initialise(SPEC.model_dump_json(), ImpactPolicy().model_dump_json())
    produced = runner.restore(runner._work((candidate.path, candidate.sha256, candidate.data)))

    assert produced == runner.examine(candidate, SPEC, ImpactPolicy())


def test_a_worker_that_was_never_initialised_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """The executor always initialises first, so reaching this is a defect."""
    monkeypatch.setattr(runner, "_WORKER", None)
    with pytest.raises(RuntimeError, match="obelize defect"):
        runner._work(("app.py", "0" * 64, b""))


def test_a_spec_the_worker_was_given_is_the_spec_it_uses() -> None:
    """`_initialise` rebuilds both arguments once per process, not once per file."""
    runner._initialise(SPEC.model_dump_json(), ImpactPolicy(import_policy="dual").model_dump_json())
    worker = runner._WORKER

    assert worker is not None
    assert worker.spec == SPEC
    assert worker.policy.import_policy == "dual"


def result(path: str, digest: str) -> runner.FileResult:
    return runner.FileResult(path=path, sha256=digest, parsed=False, plan=ImpactPlan(path=path))


def test_the_sort_key_is_the_path_bytes_and_then_the_hash() -> None:
    """`tests/oracle/test_scan_determinism.py` asserts what the key is for."""
    assert runner.sort_key(result("pkg/a.py", "ab" * 32)) == (b"pkg/a.py", "ab" * 32)


def test_a_result_that_was_never_read_sorts_before_one_that_was() -> None:
    unread, read = result("a.py", ""), result("a.py", "0" * 64)

    assert runner.ordered([read, unread]) == (unread, read)


# A model another module imports must not be deleted with its constructor: the importer breaks.
HOLDER = """import acme.sdk as sdk

sdk.configure(key="k")

M = sdk.Model("m")


def go(text):
    return M.run(text).words
"""

DESK = """import acme.sdk as sdk


class Desk:
    def __init__(self):
        sdk.configure(key="k")
        self.model = sdk.Model("m")

    def go(self, text):
        return self.model.run(text).words
"""


def binding(scan: runner.Scan, path: str) -> tuple[str, str | None]:
    row = next(row for row in scan.bindings if row.path == path)
    return row.scan_status, row.bail


@pytest.mark.parametrize(
    ("holder", "reader"),
    [
        ("llm.py", "from llm import M\n\nprint(M)\n"),
        ("llm.py", "from llm import *\n"),
        ("llm.py", "import llm\n\nprint(llm.M)\n"),
        ("pkg/llm.py", "from pkg.llm import M\n"),
        ("pkg/llm.py", "from .llm import M\n"),
        ("pkg/llm.py", "from . import llm\n\nprint(llm.M)\n"),
        ("pkg/llm.py", "import pkg.llm as backend\n\nprint(backend.M)\n"),
        ("pkg/__init__.py", "from pkg import M\n"),
    ],
)
def test_a_module_constant_another_module_imports_is_withheld(
    tmp_path: Path, holder: str, reader: str
) -> None:
    files = {holder: HOLDER, "pkg/app.py": reader}
    if holder != "pkg/__init__.py":
        files.setdefault("pkg/__init__.py", "")
    result = scanned(tree(tmp_path, files))
    assert binding(result, holder) == ("needs_review", "model_object_read_elsewhere")
    rows = [row for row in result.findings if row.path == holder]
    assert {(row.line, row.bail) for row in rows if row.line in (5, 9)} == {
        (5, "model_object_read_elsewhere"),
        (9, "model_object_read_elsewhere"),
    }
    assert {row.bail for row in rows if row.line in (1, 3)} == {"file_not_fully_migrated"}


def test_an_instance_attribute_another_module_reads_is_withheld(tmp_path: Path) -> None:
    reader = "from desk import Desk\n\nprint(Desk().model.run('x'))\n"
    result = scanned(tree(tmp_path, {"desk.py": DESK, "app.py": reader}))
    assert binding(result, "desk.py") == ("needs_review", "model_object_read_elsewhere")


@pytest.mark.parametrize(
    "reader",
    [
        '"""M is built in llm, and nothing here imports it."""\n\nM = 1\n',
        "import llm\n\nM = llm.go\n",
        "from llm import go\n\nM = go\n",
        "from other import M\n",
    ],
    ids=["prose", "another-name", "another-import", "another-module"],
)
def test_a_module_that_does_not_reach_the_model_changes_nothing(
    tmp_path: Path, reader: str
) -> None:
    result = scanned(tree(tmp_path, {"llm.py": HOLDER, "app.py": reader}))
    assert binding(result, "llm.py") == ("eligible", None)


def test_an_instance_attribute_nobody_else_reads_changes_nothing(tmp_path: Path) -> None:
    reader = "from desk import Desk\n\nprint(Desk().go('x'))\n"
    result = scanned(tree(tmp_path, {"desk.py": DESK, "app.py": reader}))
    assert binding(result, "desk.py") == ("eligible", None)


def test_an_instance_attribute_read_off_something_else_changes_nothing(tmp_path: Path) -> None:
    result = scanned(tree(tmp_path, {"desk.py": DESK, "app.py": "print(other.model)\n"}))
    assert binding(result, "desk.py") == ("eligible", None)


def test_a_function_s_own_model_is_not_another_module_s(tmp_path: Path) -> None:
    """A local is nobody else's to import, whatever another module reads."""
    holder = (
        "import acme.sdk as sdk\n\nsdk.configure(key='k')\n\n\n"
        "def go(p):\n    model = sdk.Model('m')\n    return model.run(p).words\n"
    )
    result = scanned(
        tree(tmp_path, {"llm.py": holder, "app.py": "import llm\n\nprint(llm.model)\n"})
    )
    assert binding(result, "llm.py") == ("eligible", None)


def test_a_group_already_withheld_keeps_its_own_code(tmp_path: Path) -> None:
    holder = HOLDER + "\nREGISTRY = [M]\n"
    result = scanned(tree(tmp_path, {"llm.py": holder, "app.py": "from llm import M\n"}))
    assert binding(result, "llm.py") == ("needs_review", "model_object_escapes")


def test_a_file_already_withheld_for_another_group_names_this_one_too(tmp_path: Path) -> None:
    """File atomicity is recomputed with the new bail, so `caused_by` names both causes."""
    holder = HOLDER + "\nA = sdk.Model('a')\nREGISTRY = [A]\n"
    result = scanned(tree(tmp_path, {"llm.py": holder, "app.py": "from llm import M\n"}))
    rows = {row.line: (row.bail, row.caused_by) for row in result.findings if row.path == "llm.py"}
    assert rows[5] == ("model_object_read_elsewhere", None)
    assert rows[1] == (
        "file_not_fully_migrated",
        ("model_object_escapes", "model_object_read_elsewhere"),
    )


def test_a_module_that_never_names_the_model_is_not_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed: list[bytes] = []
    real = ast.parse

    def spy(source: str | bytes, *args: Any, **kwargs: Any) -> Any:
        # Bytes are this pass's; pytest and coverage parse text of their own.
        if isinstance(source, bytes):
            parsed.append(source)
        return real(source, *args, **kwargs)

    monkeypatch.setattr(ast, "parse", spy)
    scanned(tree(tmp_path, {"llm.py": HOLDER, "app.py": "print('hello')\n"}))
    assert parsed == [HOLDER.encode()]


@pytest.mark.skipif(AS_ROOT, reason="root reads a file it may not")
def test_a_module_that_cannot_be_read_is_not_a_reader(tmp_path: Path) -> None:
    """What it imports is unknown."""
    root = tree(tmp_path, {"llm.py": HOLDER, "app.py": "from llm import M\n"})
    with deny(root / "app.py"):
        result = scanned(root)
    assert binding(result, "llm.py") == ("eligible", None)


def test_a_module_that_is_gone_when_the_readers_are_gathered_is_left_out(tmp_path: Path) -> None:
    """Windows stops a denied module at the walk, so the failed read is shown by a missing one."""
    root = tree(tmp_path, {"llm.py": HOLDER})
    assert list(reach._trees(root, ["gone.py", "llm.py"], {"M"})) == ["llm.py"]


def test_a_module_that_does_not_parse_is_not_a_reader(tmp_path: Path) -> None:
    """Python cannot import it either."""
    result = scanned(tree(tmp_path, {"llm.py": HOLDER, "app.py": "from llm import M\ndef (:\n"}))
    assert binding(result, "llm.py") == ("eligible", None)
