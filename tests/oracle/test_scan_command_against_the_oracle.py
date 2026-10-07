"""`obelize scan` on the oracle cases prints the bytes of the document `runner.scan` yields.

Exclusions reach the command through a real `.obelize.yml`. Bytes, not fields: `docs/CLI.md`
promises bytes. A second run scans the first one's `.obelize/`, which must stay excluded.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import harness
import pytest
from typer.testing import CliRunner, Result

from obelize import __version__
from obelize.cli import app
from obelize.models import FindingsDocument, PackRef
from obelize.packs import loader
from obelize.scan import walker

runner = CliRunner()
CASE_NAMES = sorted(harness.CASES)

# The `.obelize.yml` keys a scan reads; the rest configure verification and the model adapter.
SELECTION_KEYS = ("include", "exclude", "max_file_bytes")


def _corpus(name: str, into: Path) -> Path:
    """Copy a case byte for byte, as the encoding fixtures need, symlinks kept, with exclusions."""
    source, config, _spec = harness.configured(name)
    root = into / name
    shutil.copytree(source, root, symlinks=True)
    assert SELECTION_KEYS == ("include", "exclude", "max_file_bytes")
    lines = [f"include: {json.dumps(config.include)}", "exclude:"]
    lines.extend(f"  - {json.dumps(pattern)}" for pattern in config.exclude)
    lines.append(f"max_file_bytes: {config.max_file_bytes}")
    (root / ".obelize.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def _expected(name: str) -> bytes:
    """The API's document for this case, as bytes."""
    case = harness.load(name)
    pack = loader.load(harness.BUNDLED_PACK)
    document = FindingsDocument(
        obelize_version=__version__,
        packs=(PackRef(id=pack.pack.id, version=pack.pack.pack_version, sha256=pack.sha256),),
        counts=case.scan.counts,
        findings=case.scan.findings,
    )
    return document.model_dump_json(indent=2).encode("utf-8") + b"\n"


def _scan(root: Path, *extra: str) -> Result:
    return runner.invoke(app, ["scan", "--repo", str(root), "--pack", harness.BUNDLED_PACK, *extra])


@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_command_produces_the_document_the_passes_produce(name: str, tmp_path: Path) -> None:
    """The command composes the passes; nothing it adds may show in the answer."""
    root = _corpus(name, tmp_path)
    result = _scan(root, "--json")
    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == _expected(name)


@pytest.mark.parametrize("name", CASE_NAMES)
def test_two_runs_are_byte_identical_across_the_run_folder_the_first_one_wrote(
    name: str, tmp_path: Path
) -> None:
    root = _corpus(name, tmp_path)
    first = _scan(root, "--json")
    assert (root / ".obelize" / "latest").is_file()
    second = _scan(root, "--json")
    assert first.stdout_bytes == second.stdout_bytes
    assert len(list((root / ".obelize" / "runs").iterdir())) == 2


@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_worker_count_is_not_part_of_the_answer(name: str, tmp_path: Path) -> None:
    root = _corpus(name, tmp_path)
    one = _scan(root, "--json", "--jobs", "1")
    many = _scan(root, "--json", "--jobs", "4")
    assert one.stdout_bytes == many.stdout_bytes


@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_run_folder_holds_the_same_document_that_was_printed(name: str, tmp_path: Path) -> None:
    root = _corpus(name, tmp_path)
    result = _scan(root, "--json")
    latest = (root / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    folder = root / ".obelize" / "runs" / latest
    assert (folder / "findings.json").read_bytes() == result.stdout_bytes
    record = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert record["counts"]["findings"] == json.loads(result.stdout)["counts"]["findings"]
    assert record["run_id"] == latest


@pytest.mark.parametrize("name", CASE_NAMES)
def test_list_files_prints_the_selection_the_walker_made(name: str, tmp_path: Path) -> None:
    """The flag inspects exclusions, so it prints the walker's selection, not a second list."""
    root = _corpus(name, tmp_path)
    source, config, _spec = harness.configured(name)
    result = _scan(root, "--list-files")
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == list(walker.walk(source, config).files)


def test_the_command_agrees_with_itself_in_a_second_interpreter(tmp_path: Path) -> None:
    """Real processes: a `CliRunner` shares this heap, and libcst's set order is per process."""
    root = _corpus("escapes", tmp_path)
    runs = [
        subprocess.run(
            [sys.executable, "-m", "obelize.cli", "scan", "--repo", str(root), "--json"],
            capture_output=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("0", "1")
    ]
    assert runs[0] == runs[1]
    assert runs[0] == _expected("escapes")
