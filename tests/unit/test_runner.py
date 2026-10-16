"""`runner.scan` beyond the oracle: files no worker sees, the pool boundary, when to pool."""

from __future__ import annotations

import ast
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import acme
import pytest
from acme import SPEC
from pdf_repo import MAIN, REMOVED, git_repo
from pdf_repo import SPEC as PDF

from obelize.config import ConfigError
from obelize.impact import planner
from obelize.models import Config, ImpactPlan
from obelize.native import processes
from obelize.packs import loader
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


def scanned(root: Path, config: Config | None = None, jobs: int | None = None) -> runner.Scan:
    return runner.scan(root, config or Config(), SPEC, jobs=jobs)


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
    root = tree(tmp_path, {"pyproject.toml": "[project\n", "app.py": LEGACY})
    scan = scanned(root)
    assert scan.blocked == ()
    assert [(row.path, row.code) for row in scan.limitations] == [
        ("pyproject.toml", "input_does_not_parse")
    ]


def test_a_legacy_pin_below_the_packs_floor_blocks_the_scan(tmp_path: Path) -> None:
    root = tree(tmp_path, {"app.py": "import acme.old\n\nacme.old.Reader(1)\n"})
    (root / "requirements.txt").write_text("acme-old>=1\n", encoding="utf-8")
    scan = runner.scan(root, Config(), acme.OLD_SPEC, jobs=1)
    assert [(row.reason, row.path, row.declared) for row in scan.blocked] == [
        ("legacy_version_unsupported", "requirements.txt", ">=1")
    ]


def test_a_pin_inside_the_range_and_a_repository_that_never_uses_the_library_are_not_blocked(
    tmp_path: Path,
) -> None:
    used = tree(tmp_path / "used", {"app.py": "import acme.old\n\nacme.old.Reader(1)\n"})
    (used / "requirements.txt").write_text("acme-old>=2,<3\n", encoding="utf-8")
    assert runner.scan(used, Config(), acme.OLD_SPEC, jobs=1).blocked == ()

    unused = tree(tmp_path / "unused", {"app.py": "import os\n"})
    assert runner.scan(unused, Config(), acme.OLD_SPEC, jobs=1).blocked == ()


def test_a_library_used_with_no_declaration_blocks_the_scan(tmp_path: Path) -> None:
    root = tree(tmp_path, {"app.py": "import acme.old\n\nacme.old.Reader(1)\n"})
    scan = runner.scan(root, Config(), acme.OLD_SPEC, jobs=1)
    assert [row.path for row in scan.blocked] == [""]


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

    runner._initialise(SPEC.model_dump_json())
    produced = runner.restore(runner._work((candidate.path, candidate.sha256, candidate.data)))

    assert produced == runner.examine(candidate, SPEC)


def test_a_file_too_deep_for_the_analysis_is_one_unparsable_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The trees that parse still overrun the visitors' stack when nested deeply enough."""
    real = analysis.analyse

    def overrun(read: parse.Read, spec: Any) -> Any:
        if read.module is not None:
            raise RecursionError
        return real(read, spec)

    monkeypatch.setattr(analysis, "analyse", overrun)
    candidate = runner.Candidate(path="app.py", sha256="0" * 64, data=LEGACY.encode())

    result = runner.examine(candidate, SPEC)

    assert result.parsed is False
    assert [finding.bail for finding in result.plan.findings] == ["input_does_not_parse"]
    assert [row.code for row in result.limitations] == ["input_does_not_parse"]


def _raise_on(monkeypatch: pytest.MonkeyPatch, path: str, error: Exception) -> None:
    """Make the analysis of one file's tree raise, as a defect in obelize would."""
    real = analysis.analyse

    def analyse(read: parse.Read, spec: Any) -> Any:
        if read.path == path and read.module is not None:
            raise error
        return real(read, spec)

    monkeypatch.setattr(analysis, "analyse", analyse)


def test_an_unexpected_error_on_one_file_is_that_files_refusal_and_not_the_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row says which class, never the message, which can quote the file or a path."""
    _raise_on(monkeypatch, "bad.py", KeyError("/home/me/bad.py: sk-123"))
    scan = scanned(tree(tmp_path, {"bad.py": LEGACY, "good.py": LEGACY}))

    assert (at(scan, "bad.py").parsed, at(scan, "good.py").parsed) == (False, True)
    assert [(row.kind, row.scan_status, row.bail) for row in at(scan, "bad.py").plan.findings] == [
        ("parse_error", "unsupported", "internal_error")
    ]
    assert {row.scan_status for row in at(scan, "good.py").plan.findings} == {"eligible"}
    [limitation] = scan.limitations
    assert (limitation.path, limitation.code) == ("bad.py", "internal_error")
    assert limitation.detail.endswith("It raised KeyError.")
    assert "sk-123" not in limitation.detail
    assert scan.counts.files_parsed == 1


def test_a_file_obelize_raised_on_holds_the_pin_as_an_unparsable_one_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It may import the legacy SDK, so the dependency line stays: removing it could break it."""
    files = {"app.py": LEGACY, "requirements.txt": MANIFEST}
    refused = scanned(tree(tmp_path / "unparsable", {**files, "app.py": BROKEN}))
    assert [row.scan_status for row in refused.manifests.findings] == ["needs_review"]

    _raise_on(monkeypatch, "app.py", RuntimeError())
    raised = scanned(tree(tmp_path / "raised", files))
    assert [(row.scan_status, row.bail) for row in raised.manifests.findings] == [
        (row.scan_status, row.bail) for row in refused.manifests.findings
    ]


def test_an_error_while_gating_a_file_is_its_refusal_too(monkeypatch: pytest.MonkeyPatch) -> None:
    def overrun(path: str, data: bytes) -> parse.Read:
        raise ValueError("a gate raised outside the type it documents")

    monkeypatch.setattr(parse, "gates", overrun)
    candidate = runner.Candidate(path="app.py", sha256="0" * 64, data=LEGACY.encode())

    result = runner.examine(candidate, SPEC)

    assert result.parsed is False
    assert [row.code for row in result.limitations] == ["internal_error"]
    assert result.limitations[0].detail.endswith("It raised ValueError.")


def test_a_refusal_for_an_error_crosses_the_pool_boundary_as_plain_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _raise_on(monkeypatch, "app.py", RuntimeError())
    candidate = runner.Candidate(path="app.py", sha256="0" * 64, data=LEGACY.encode())
    result = runner.examine(candidate, SPEC)

    assert runner.restore(json.loads(json.dumps(runner.payload(result)))) == result


def test_a_worker_that_was_never_initialised_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """The executor always initialises first, so reaching this is a defect."""
    monkeypatch.setattr(runner, "_SPEC", None)
    with pytest.raises(RuntimeError, match="obelize defect"):
        runner._work(("app.py", "0" * 64, b""))


def test_a_spec_the_worker_was_given_is_the_spec_it_uses() -> None:
    """`_initialise` rebuilds the spec once per process, not once per file."""
    runner._initialise(SPEC.model_dump_json())

    assert runner._SPEC == SPEC


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


def test_a_module_that_names_neither_the_model_nor_its_module_is_not_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed: list[bytes] = []
    real = ast.parse

    def spy(source: str | bytes, *args: Any, **kwargs: Any) -> Any:
        # Bytes are the scan's: pytest and coverage parse text of their own.
        if isinstance(source, bytes):
            parsed.append(source)
        return real(source, *args, **kwargs)

    monkeypatch.setattr(ast, "parse", spy)
    reader = "from llm import M\n"
    files = {"llm.py": HOLDER, "app.py": reader, "plain.py": "print('hello')\n"}
    # Its name without its module, and its module without its name.
    scanned(tree(tmp_path, {**files, "same.py": "M = 1\n", "twin.py": "import llm\n"}))
    # The depth check parses the one candidate; this pass, only the reader.
    assert parsed == [HOLDER.encode(), reader.encode()]


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
    trees = reach._trees(parse.disk(root, Config()), ["gone.py", "llm.py"], {"M"}, {"sdk"})
    assert list(trees) == ["llm.py"]


def test_a_module_that_does_not_parse_is_not_a_reader(tmp_path: Path) -> None:
    """Python cannot import it either."""
    result = scanned(tree(tmp_path, {"llm.py": HOLDER, "app.py": "from llm import M\ndef (:\n"}))
    assert binding(result, "llm.py") == ("eligible", None)


# The newest release stands in for a version nobody wrote down, and only where nothing says
# otherwise (ADR-056): each tree below is a real git repository, since only a git listing names
# every file, a dot-directory's and an ignored one's among them.

NEWEST = (("PyPDF2", "3.0.1"),)
HASHED = "pypdf2==1.26.0 \\\n    --hash=sha256:aaaa\n"
STANDS_IN: dict[str, dict[str, str | bytes]] = {
    "bare": {"requirements.txt": "PyPDF2\n"},
    "open-range": {"requirements.txt": "PyPDF2>=2.10\n"},
    "upper-bound-only": {"requirements.txt": "PyPDF2<4\n"},
    "two-bounds": {"requirements.txt": "PyPDF2>=2,<4\n"},
    "poetry": {"pyproject.toml": '[tool.poetry.dependencies]\nPyPDF2 = "*"\n'},
    "pipfile": {"Pipfile": '[packages]\nPyPDF2 = "*"\n'},
    "setup-py": {"setup.py": 'from setuptools import setup\nsetup(install_requires=["PyPDF2"])\n'},
    "requirements-and-input-files-that-say-nothing-of-it": {
        "requirements.txt": "PyPDF2\n",
        "dev-requirements.txt": "pytest\n",
        "requirements.in": "flask\n",
        "constraints.txt": "flask==2\nPyPDF2>=3\n",
    },
    "options-that-do-not-move-it": {
        "requirements.txt": "-r requirements-b.txt\n--extra-index-url https://x/simple\nPyPDF2\n",
        "requirements-b.txt": "six\n",
    },
}
HELD_BACK: dict[str, tuple[dict[str, str | bytes], str, str]] = {
    "lock-file": ({"requirements.txt": "PyPDF2\n", "poetry.lock": "x\n"}, "", "poetry.lock"),
    "ignored-lock-file": (
        {"requirements.txt": "PyPDF2\n", "Pipfile.lock": "{}\n"},
        "Pipfile.lock\n",
        "Pipfile.lock",
    ),
    "include-of-an-unread-file": (
        {"requirements.txt": "-r base.txt\nPyPDF2\n", "base.txt": "PyPDF2<3\n"},
        "",
        "requirements.txt",
    ),
    "private-index": (
        {"requirements.txt": "-i https://private.example/simple\nPyPDF2\n"},
        "",
        "requirements.txt",
    ),
    "exclude-newer": (
        {
            "requirements.txt": "PyPDF2\n",
            "pyproject.toml": '[tool.uv]\nexclude-newer = "2022-01-01"\n',
        },
        "",
        "pyproject.toml",
    ),
    "pipfile-private-source": (
        {
            "Pipfile": '[[source]]\nurl = "https://private.example/simple"\nname = "private"\n\n'
            '[packages]\nPyPDF2 = "*"\n'
        },
        "",
        "Pipfile",
    ),
    "utf-16-export": (
        {
            "requirements.txt": "PyPDF2\n",
            "requirements-freeze.txt": "PyPDF2==1.26.0\n".encode("utf-16"),
        },
        "",
        "requirements-freeze.txt",
    ),
    "dockerfile": (
        {"requirements.txt": "PyPDF2\n", "Dockerfile": "RUN pip install PyPDF2==1.26.0\n"},
        "",
        "Dockerfile",
    ),
    "notebook": (
        {
            "requirements.txt": "PyPDF2\n",
            "nb.ipynb": '{"cells": [{"source": ["!pip install PyPDF2==1.26.0"]}]}\n',
        },
        "",
        "nb.ipynb",
    ),
    "ci-file": (
        {
            "requirements.txt": "PyPDF2\n",
            ".github/workflows/ci.yml": "- run: pip install 'PyPDF2<3'\n",
        },
        "",
        ".github/workflows/ci.yml",
    ),
    "ignored-environment": (
        {
            "requirements.txt": "PyPDF2\n",
            ".venv/lib/python3.9/site-packages/PyPDF2-1.26.0.dist-info/METADATA": "x\n",
        },
        ".venv/\n",
        ".venv/lib/python3.9/site-packages/PyPDF2-1.26.0.dist-info",
    ),
    "code-the-newest-release-cannot-run": (
        {"requirements.txt": "PyPDF2\n", "main.py": REMOVED},
        "",
        "main.py",
    ),
}


# Declarations the scan reads but cannot honour: the row itself blocks, with no evidence to name.
UNHONOURED: dict[str, tuple[dict[str, str | bytes], str, str | None]] = {
    "hashed-lowercase-export": (
        {"requirements.txt": "PyPDF2\n", "requirements-lock.txt": HASHED},
        "requirements-lock.txt",
        "==1.26.0",
    ),
    "editable-egg": (
        {"requirements.txt": "PyPDF2\n-e git+https://host/repo#egg=PyPDF2\n"},
        "requirements.txt",
        None,
    ),
    "wheel-url": (
        {
            "requirements.txt": "PyPDF2\n",
            "requirements-extra.txt": "https://host/PyPDF2-1.26.0-py3-none-any.whl\n",
        },
        "requirements-extra.txt",
        None,
    ),
    "constraints-file": (
        {"requirements.txt": "-c constraints.txt\nPyPDF2\n", "constraints.txt": "PyPDF2<3\n"},
        "constraints.txt",
        "<3",
    ),
    "own-table": (
        {
            "requirements.txt": "PyPDF2\n",
            "pyproject.toml": '[tool.poetry.dependencies.PyPDF2]\nversion = "^1.26"\n',
        },
        "pyproject.toml",
        "^1.26",
    ),
}


def gated(root: Path, spec: Any = PDF, config: Config | None = None) -> runner.Scan:
    return runner.scan(root, config or Config(), spec, jobs=1)


def repository(root: Path, files: Mapping[str, str | bytes], ignore: str = "") -> Path:
    """The PyPDF2 code the gate is asked about, beside `files`, as a git repository."""
    return git_repo(root, {"main.py": MAIN, **files}, ignore)


@pytest.mark.parametrize("name", STANDS_IN)
def test_a_declaration_that_names_no_version_that_rules_the_newest_out_is_taken_as_it(
    tmp_path: Path, name: str
) -> None:
    scan = gated(repository(tmp_path, STANDS_IN[name]))
    assert scan.blocked == ()
    assert scan.assumed == NEWEST
    assert scan.source == "git"


@pytest.mark.parametrize("name", STANDS_IN)
def test_the_same_repository_is_blocked_by_a_pack_that_names_no_newest_release(
    tmp_path: Path, name: str
) -> None:
    """The field is the pack's claim: without it the gate is the one ADR-050 describes."""
    scan = gated(
        repository(tmp_path, STANDS_IN[name]), PDF.model_copy(update={"legacy_newest": None})
    )
    assert [(row.reason, row.evidence) for row in scan.blocked] == [
        ("legacy_version_unsupported", "")
    ]
    assert scan.assumed == ()


@pytest.mark.parametrize("name", HELD_BACK)
def test_a_repository_that_shows_another_release_is_blocked_and_names_the_path(
    tmp_path: Path, name: str
) -> None:
    files, ignore, evidence = HELD_BACK[name]
    scan = gated(repository(tmp_path, files, ignore))
    assert [(row.reason, row.package, row.evidence) for row in scan.blocked] == [
        ("legacy_version_unsupported", "PyPDF2", evidence)
    ]
    assert scan.assumed == ()


@pytest.mark.parametrize("name", HELD_BACK)
def test_what_holds_the_newest_release_back_is_not_what_blocks_without_it(
    tmp_path: Path, name: str
) -> None:
    """The same trees are stopped by the declaration alone, with no evidence named."""
    files, ignore, _evidence = HELD_BACK[name]
    spec = PDF.model_copy(update={"legacy_newest": None})
    scan = gated(repository(tmp_path, files, ignore), spec)
    assert [row.evidence for row in scan.blocked] == [""]


@pytest.mark.parametrize("name", UNHONOURED)
def test_a_declaration_the_gate_cannot_honour_blocks_at_its_own_line(
    tmp_path: Path, name: str
) -> None:
    files, path, declared = UNHONOURED[name]
    scan = gated(repository(tmp_path, files))
    assert [(row.reason, row.path, row.declared, row.evidence) for row in scan.blocked] == [
        ("legacy_version_unsupported", path, declared, "")
    ]


def test_a_requirement_built_around_its_string_has_no_pin_so_it_is_not_taken(
    tmp_path: Path,
) -> None:
    setup = 'from setuptools import setup\nV = ">=3"\nsetup(install_requires=["PyPDF2" + V])\n'
    scan = gated(repository(tmp_path, {"requirements.txt": "PyPDF2\n", "setup.py": setup}))
    assert [(row.path, row.evidence) for row in scan.blocked] == [("setup.py", "")]
    assert scan.assumed == ()


def test_a_manifest_the_scan_cannot_read_whole_is_evidence(tmp_path: Path) -> None:
    files = {"requirements.txt": "PyPDF2\n", "requirements-big.txt": "six\n" * 100}
    scan = gated(repository(tmp_path, files), config=Config(max_file_bytes=200))
    assert [row.evidence for row in scan.blocked] == ["requirements-big.txt"]
    assert scan.assumed == ()


def test_a_pin_that_already_reaches_the_floor_takes_no_assumption(tmp_path: Path) -> None:
    for index, pin in enumerate(["PyPDF2==3.0.1", "PyPDF2>=3", "PyPDF2~=3.0"]):
        scan = gated(repository(tmp_path / str(index), {"requirements.txt": f"{pin}\n"}))
        assert (scan.blocked, scan.assumed) == ((), ()), pin


def test_the_machine_that_scans_decides_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No `PIP_*` variable and no user `pip.conf` is read, so a finding is the same on every
    machine that scans the same files (ADR-056)."""
    root = repository(tmp_path / "repo", {"requirements.txt": "PyPDF2\n"})
    plain = gated(root)
    home = tmp_path / "home"
    (home / ".config" / "pip").mkdir(parents=True)
    conf = home / ".config" / "pip" / "pip.conf"
    conf.write_text("[global]\nindex-url = https://host/simple\nconstraint = c.txt\n", "utf-8")
    for key, value in {
        "PIP_INDEX_URL": "https://host/simple",
        "PIP_CONSTRAINT": str(tmp_path / "c.txt"),
        "PIP_FIND_LINKS": str(tmp_path),
        "PIP_NO_INDEX": "1",
        "PIP_CONFIG_FILE": str(conf),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }.items():
        monkeypatch.setenv(key, value)
    scan = gated(root)
    assert (scan.blocked, scan.assumed) == ((), NEWEST)
    assert scan == plain


def test_a_second_declaration_below_the_floor_still_blocks_and_names_no_evidence(
    tmp_path: Path,
) -> None:
    files = {"requirements.txt": "PyPDF2\n", "requirements-old.txt": "PyPDF2<3\n"}
    scan = gated(repository(tmp_path, files))
    assert [(row.path, row.declared, row.evidence) for row in scan.blocked] == [
        ("requirements-old.txt", "<3", "")
    ]
    assert scan.assumed == ()


@pytest.mark.parametrize("pin", ["pypdf==3.0.0", "pypdf<6", "pypdf~=3.0", "pypdf>3,<6.19"])
def test_a_pin_of_pypdf_that_admits_no_release_the_pack_writes_blocks_at_its_own_line(
    tmp_path: Path, pin: str
) -> None:
    """Whatever PyPDF2 says: the other pin would resolve, to a release without the new names."""
    for index, legacy in enumerate(["PyPDF2>=3", "PyPDF2"]):
        files = {"requirements.txt": f"{legacy}\n", "requirements-dev.txt": f"{pin}\n"}
        scan = gated(repository(tmp_path / str(index), files))
        assert [(r.reason, r.package, r.path, r.needed) for r in scan.blocked] == [
            ("new_version_unsupported", "pypdf", "requirements-dev.txt", ">=6.19")
        ]
        assert scan.assumed == ()


@pytest.mark.parametrize("pin", ["pypdf>=6.19", "pypdf>=3", "pypdf", "pypdf==6.19.0", "pypdf<7"])
def test_a_pin_of_pypdf_that_admits_a_release_the_pack_writes_blocks_nothing(
    tmp_path: Path, pin: str
) -> None:
    files = {"requirements.txt": "PyPDF2>=3\n", "requirements-dev.txt": f"{pin}\n"}
    assert gated(repository(tmp_path, files)).blocked == ()


def test_a_marker_or_a_pre_release_is_never_taken_as_the_newest_release(tmp_path: Path) -> None:
    for index, line in enumerate(['PyPDF2; python_version < "3.12"', "PyPDF2>=3.0.0rc1"]):
        scan = gated(repository(tmp_path / str(index), {"requirements.txt": f"{line}\n"}))
        assert [row.reason for row in scan.blocked] == ["legacy_version_unsupported"], line
        assert (scan.blocked[0].evidence, scan.assumed) == ("", ()), line


def test_a_pin_that_pip_may_not_use_is_never_taken(tmp_path: Path) -> None:
    for index, line in enumerate(["PyPDF2[crypto]", "PyPDF2 @ https://host/PyPDF2.whl"]):
        scan = gated(repository(tmp_path / str(index), {"requirements.txt": f"{line}\n"}))
        assert [row.reason for row in scan.blocked] == ["legacy_version_unsupported"], line
        assert (scan.blocked[0].evidence, scan.assumed) == ("", ()), line


def test_a_directory_that_is_not_a_repository_is_never_assumed(tmp_path: Path) -> None:
    """Without a git listing a pin in a dot-directory could not be seen."""
    root = git_repo(tmp_path, {"main.py": MAIN, "requirements.txt": "PyPDF2\n"}, init=False)
    scan = gated(root)
    assert scan.source == "walk"
    assert [(row.reason, row.path, row.evidence) for row in scan.blocked] == [
        ("legacy_version_unsupported", "requirements.txt", "")
    ]
    assert scan.assumed == ()
    assert scan.blocked[0].unlisted is True


def test_a_directory_below_the_top_of_a_repository_is_unlisted_and_one_at_the_top_is_not(
    tmp_path: Path,
) -> None:
    """The block says what to do only where the missing listing is what stopped the inference."""
    top = repository(tmp_path / "top", {"requirements.txt": "PyPDF2<3\n"})
    assert gated(top).blocked[0].unlisted is False
    below = git_repo(
        tmp_path / "top" / "sub", {"main.py": MAIN, "requirements.txt": "PyPDF2\n"}, init=False
    )
    scan = gated(below)
    assert (scan.source, scan.blocked[0].unlisted) == ("walk", True)
    spec = PDF.model_copy(update={"legacy_newest": None})
    assert gated(below, spec).blocked[0].unlisted is False


def test_a_library_nothing_uses_is_not_blocked_and_nothing_is_assumed(tmp_path: Path) -> None:
    scan = gated(repository(tmp_path, {"main.py": "import os\n", "requirements.txt": "PyPDF2\n"}))
    assert (scan.blocked, scan.assumed) == ((), ())


def test_a_library_declared_nowhere_is_still_blocked_with_nothing_assumed(tmp_path: Path) -> None:
    scan = gated(repository(tmp_path, {}))
    assert [(row.path, row.declared, row.evidence) for row in scan.blocked] == [("", None, "")]
    assert scan.assumed == ()


FLOORS: dict[str, dict[str, str | bytes]] = {
    "pyproject": {"pyproject.toml": '[project]\nname = "x"\nrequires-python = ">=3.7"\n'},
    "pipfile": {"Pipfile": '[requires]\npython_version = "3.7"\n'},
    "setup-py": {"setup.py": 'from setuptools import setup\nsetup(python_requires=">=3.6")\n'},
}


@pytest.mark.parametrize("name", FLOORS)
def test_a_python_the_new_distribution_does_not_install_on_is_the_block_not_the_newest_release(
    tmp_path: Path, name: str
) -> None:
    scan = gated(repository(tmp_path, {"requirements.txt": "PyPDF2\n", **FLOORS[name]}))
    assert [(row.reason, row.evidence) for row in scan.blocked] == [("runtime_unsupported", "")]
    assert scan.assumed == ()


def test_only_the_pack_that_names_a_newest_release_takes_one() -> None:
    named = {
        identifier: (spec.legacy_newest, spec.legacy_lacks)
        for identifier in loader.bundled_ids()
        for spec in [loader.to_scan_spec(loader.load(identifier))]
    }
    assert named == {
        "gemini/google-generativeai-to-google-genai": (None, ()),
        "openai/openai-0-to-1": (None, ()),
        "py-pdf/pypdf2-to-pypdf": (
            "3.0.1",
            ("PyPDF2.PdfFileMerger", "PyPDF2.PdfFileReader", "PyPDF2.PdfFileWriter"),
        ),
    }


def test_a_library_with_no_newest_release_is_blocked_as_before(tmp_path: Path) -> None:
    """openai's newest release (3.x) is outside the range its pack migrates from."""
    spec = loader.to_scan_spec(loader.load("openai/openai-0-to-1"))
    code = "import openai\n\nopenai.api_key = 'k'\nopenai.ChatCompletion.create(model='m')\n"
    root = git_repo(tmp_path, {"app.py": code, "requirements.txt": "openai\n"})
    scan = gated(root, spec)
    assert [(row.reason, row.package, row.evidence) for row in scan.blocked] == [
        ("legacy_version_unsupported", "openai", "")
    ]
    assert scan.assumed == ()


def test_scans_of_several_packs_keep_what_each_assumed(tmp_path: Path) -> None:
    """`merged` unions the pairs, and a pack that assumed nothing adds none."""
    root = repository(tmp_path, {"requirements.txt": "PyPDF2\n"})
    first, second = gated(root), gated(root, acme.OLD_SPEC)
    assert runner.merged([first, second], runner.read(root, Config(), (PDF,))).assumed == NEWEST
    assert runner.merged([first, first], runner.read(root, Config(), (PDF,))).assumed == NEWEST
