"""`docs/RUN_FOLDER.md` is the run folder's specification; the models and e2e.yml must match it.

Checked both ways: each table names exactly its model's fields.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from obelize.models import (
    RUN_MODES,
    CommandRecord,
    CommandResult,
    RunRecord,
    UndoFile,
    UndoRecord,
)

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "docs" / "RUN_FOLDER.md"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "e2e.yml"
SPEC = SPEC_PATH.read_text(encoding="utf-8")
WORKFLOW = WORKFLOW_PATH.read_text(encoding="utf-8")

# A jq path in the workflow, e.g. `(.pack.sha256 | test(...))` or `.idempotent == true`.
_JQ_PATH = re.compile(r"[\s(]\.([a-z_][a-z_0-9]*(?:\.[a-z_][a-z_0-9]*)*)")

# Paths e2e.yml reads from `obelize scan --json` stdout, not run.json: docs/CLI.md keeps that
# document free of anything time-derived.
NOT_RUN_JSON = {"findings"}


def _table_under(heading: str) -> list[str]:
    """Every backticked name in the first column of the first table under `heading`."""
    start = SPEC.index(heading) + len(heading)
    names: list[str] = []
    started = False
    for line in SPEC[start:].splitlines():
        if not line.startswith("|"):
            if started:
                break
            continue
        started = True
        cells = line.split("|")
        if len(cells) < 2 or set(cells[1].strip()) <= {"-", ":", " "}:
            continue
        names.extend(re.findall(r"`([a-z_][a-z_0-9]*)`", cells[1]))
    assert names, f"no table found under {heading!r} in docs/RUN_FOLDER.md"
    return names


TOP_LEVEL = set(_table_under("\n### Top level\n"))
NESTED = {
    "pack": set(_table_under("\n### `pack`\n")),
    "config": set(_table_under("\n### `config`\n")),
    "counts": set(_table_under("\n### `counts`\n")),
    "file_edits": set(_table_under("\n### `file_edits[]`\n")),
    "refused": set(_table_under("\n### `refused[]`\n")),
    "withheld": set(_table_under("\n### `withheld[]`\n")),
    "verify": set(_table_under("\n### `verify`\n")),
    "model": set(_table_under("\n### `model`\n")),
    "limitations": set(_table_under("\n### `limitations[]`\n")),
    "timings": set(_table_under("\n### `timings`\n")),
}

# Not a `RunRecord` field. Its own heading, since `_table_under` silently skips `commands[].log`.
COMMANDS = set(_table_under("\n### `verify.commands[]`\n"))
WORKFLOW_PATHS = sorted(set(_JQ_PATH.findall(WORKFLOW)) - NOT_RUN_JSON)


def test_the_specification_parses_into_the_documented_shape() -> None:
    """Guards the parsing above, so a silent zero-field parse cannot pass."""
    assert "run_id" in TOP_LEVEL
    assert len(TOP_LEVEL) >= 20, sorted(TOP_LEVEL)
    assert set(NESTED) <= TOP_LEVEL, sorted(set(NESTED) - TOP_LEVEL)
    assert WORKFLOW_PATHS, "no jq paths found in e2e.yml; the extraction regex has rotted"


@pytest.mark.parametrize("path", WORKFLOW_PATHS)
def test_every_field_the_workflow_asserts_is_specified(path: str) -> None:
    head, _, leaf = path.partition(".")
    assert head in TOP_LEVEL, (
        f"e2e.yml asserts `{path}` on run.json and docs/RUN_FOLDER.md does not define "
        f"a top-level `{head}`. Specify the field or classify it in NOT_RUN_JSON."
    )
    if leaf:
        assert head in NESTED, f"e2e.yml reads `{path}` but `{head}` has no field table"
        assert leaf in NESTED[head], (
            f"e2e.yml asserts `{path}` and the `{head}` table does not define `{leaf}`"
        )


# Fields docs/RUN_FOLDER.md says e2e.yml asserts; written out so deleting an assertion fails here.
CLAIMED_BY_THE_SPEC = [
    "run_id",
    "obelize_version",
    "mode",
    "pack.id",
    "pack.sha256",
    "git_dirty",
    "file_edits",
    "verify.status",
    "idempotent",
]


@pytest.mark.parametrize("path", CLAIMED_BY_THE_SPEC)
def test_every_field_the_specification_claims_is_asserted_really_is(path: str) -> None:
    """The page's `What e2e asserts today` stays true."""
    assert f".{path}" in WORKFLOW, (
        f"docs/RUN_FOLDER.md says e2e.yml asserts `{path}` and the workflow does not "
        f"mention it. Fix the workflow, or the section that claims it."
    )
    assert f"`{path}`" in SPEC


def test_the_latest_pointer_is_specified_the_way_the_workflow_reads_it() -> None:
    assert '$(cat "$APP_DIR/.obelize/latest")' in WORKFLOW
    assert ".obelize/latest" in SPEC
    # The workflow puts the id straight into a path: a trailing newline is the only whitespace.
    assert "trailing newline" in SPEC


def test_the_run_id_pattern_admits_what_the_specification_shows() -> None:
    """The pattern is a contract: it is the folder name and sorts chronologically."""
    pattern = re.search(r"\^\[0-9\]\{8\}T\[0-9\]\{6\}Z-\[0-9a-f\]\{8\}\$", SPEC)
    assert pattern is not None, "docs/RUN_FOLDER.md no longer pins a run id pattern"
    compiled = re.compile(pattern.group(0))
    assert compiled.fullmatch("20260917T142530Z-3f9a1c72"), "the worked example does not match"
    assert "20260917T142530Z-3f9a1c72" in SPEC
    for rejected in (
        "2026-09-17T14:25:30Z-3f9a1c72",  # colons are not legal filenames on Windows
        "20260917T142530Z-3F9A1C72",  # upper case hex
        "20260917T142530-3f9a1c72",  # no timezone marker
        "20260917T142530Z",  # no collision suffix
    ):
        assert not compiled.fullmatch(rejected), rejected


MODELLED = {
    "pack": "pack",
    "config": "config",
    "counts": "counts",
    "file_edits": "file_edits",
    "refused": "refused",
    "withheld": "withheld",
    "verify": "verify",
    "limitations": "limitations",
    "model": "model",
    "timings": "timings",
}


def _fields(name: str) -> set[str]:
    """Field names of the model behind a table: one model, or a tuple of them via `__args__`."""
    annotation = RunRecord.model_fields[name].annotation
    inner = getattr(annotation, "__args__", (annotation,))[0]
    assert isinstance(inner, type), name
    assert issubclass(inner, BaseModel), name
    return set(inner.model_fields)


def test_the_record_carries_exactly_the_fields_the_specification_names() -> None:
    assert set(RunRecord.model_fields) == TOP_LEVEL


def test_the_record_writes_the_fields_in_the_order_the_document_lists_them() -> None:
    """Not cosmetic: people read `run.json` against the table, top to bottom."""
    assert list(RunRecord.model_fields) == _table_under("\n### Top level\n")


@pytest.mark.parametrize("table", sorted(MODELLED))
def test_every_nested_table_matches_its_model(table: str) -> None:
    assert _fields(MODELLED[table]) == NESTED[table]


def test_the_command_rows_match_the_model_the_record_holds() -> None:
    """`output` can be a megabyte and `run.json` goes into bug reports: it stays under `verify/`."""
    assert set(CommandRecord.model_fields) == COMMANDS
    assert "output" not in COMMANDS
    assert "output" in set(CommandResult.model_fields)


def test_every_table_the_document_names_has_a_model_behind_it() -> None:
    assert set(NESTED) - set(MODELLED) == set()
    assert RunRecord.model_fields["model"].annotation is not type(None)


def test_a_scan_carries_no_model_and_the_document_says_so() -> None:
    """`tests/unit/test_models.py` grades the refusal; this grades that the page states it."""
    section = SPEC[SPEC.index("\n### `model`\n") :]
    assert "A scan never carries one" in SPEC[: SPEC.index("\n### `pack`\n")]
    assert "`null` whenever `model.provider` is `none`" in section


UNDO = _table_under("\n## `undo.json`\n")
UNDO_FILES = _table_under("\n### `undo.json` `files[]`\n")


def test_the_undo_document_carries_the_fields_the_specification_names() -> None:
    assert list(UndoRecord.model_fields) == UNDO
    assert list(UndoFile.model_fields) == UNDO_FILES


def test_the_undo_document_names_the_run_it_reverted_and_not_one_of_its_own() -> None:
    """`obelize undo` creates no run folder, so `mode` stays closed at three."""
    assert "run_id" in UNDO
    assert "mode" not in UNDO
    assert "undo" not in set(RUN_MODES)
