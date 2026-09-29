"""Every answer key uses only the keys its oracle reads, level by level.

A misspelt optional field (`undone:`) or an inner field without its outer block (`REQUIRES`)
asserts nothing. Prose fields (`what_it_is`, `note`, `notes`, `why`, `what`) are for reviewers.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from answer_keys import each, unknown

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"


def _load(relative: str) -> dict[str, Any]:
    loaded = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), relative
    return loaded


TRANSFORM_CASE = {"file", "what_it_is", "complete", "after", "unclaimed", "edits", "notes"}
TRANSFORM_EDIT = {"line", "rule", "status", "reason", "warnings"}

# corpus -> (top-level keys, per-edit keys); every corpus shares TRANSFORM_CASE.
TRANSFORMS = {
    "rewrite_call": ({"case", "rules", "pack", "cases"}, TRANSFORM_EDIT),
    "configure_to_client": ({"case", "rules", "pack", "cases", "notes"}, TRANSFORM_EDIT),
    "rename_import": ({"case", "rule", "pack", "cases", "notes"}, {"line", "status", "reason"}),
    "generative_model_calls": ({"case", "rules", "pack", "cases"}, TRANSFORM_EDIT),
}

COMMANDS_RUN = {
    "what", "argv", "exit_code", "mode", "file_edits", "idempotent", "refused", "verify",
    "verify_files", "snapshots", "tree", "git_dirty", "updates", "keeps", "superseded",
    "undo_of", "undo", "commit", "counts", "started", "appended", "blocked", "plan_files",
    "diff_lines", "next", "already",
}  # fmt: skip

EVIDENCE_RUN = {
    "mode", "exit_code", "git_dirty", "is_repository", "counts", "plan_files", "plan_edits",
    "file_edits", "idempotent", "refused", "withheld", "snapshots", "verify", "verify_files",
    "patch_hunks", "patch_paths", "report_sections", "verification", "allow_dirty",
}  # fmt: skip

VERIFY_CASE = {
    "case", "what_it_is", "cli", "repo", "allowlist", "approved", "mode", "answer", "asked",
    "timeout_s", "resolution", "commands", "status", "reason", "exit", "output", "env",
    "cwd_is_root", "refused", "stored", "secrets_removed", "truncated", "group_is_gone",
    "baseline", "baseline_result",
}  # fmt: skip

RUNS_TOP = {
    "case", "pack", "repository", "model", "api_key_env", "api_key", "host", "provider",
    "must_not_appear", "also_in_the_patch", "consultations", "skipped", "proposals",
    "scripts", "cases",
}  # fmt: skip

RUNS_CASE = {
    "case", "what_it_is", "configured", "argv", "exit_code", "prints_endpoint", "requests",
    "run_folder", "mode", "model", "model_dir", "tree_changed", "stderr_holds", "shows",
    "script", "git", "refused", "outcomes", "plan_files", "file_edits", "idempotent",
    "verify", "edit_proposals", "withheld_unchanged", "log_prompts", "prompts_stored",
    "repository_model",
}  # fmt: skip

SCAN_TOP = {
    "case", "after_file_is", "what_it_exercises", "findings", "bindings", "must_not_report",
    "must_not_autofix", "notes",
}  # fmt: skip
SCAN_FINDING = {
    "file", "line", "symbol", "kind", "confidence_reason", "verdict", "note", "bail",
    "warnings", "caused_by",
}  # fmt: skip
SCAN_BINDING = {
    "file", "kind", "name", "scope", "ctor_line", "use_lines", "verdict", "note", "bail",
}  # fmt: skip

# (inner, outer, how): `inner` is read only inside `outer`'s block, opened when `outer` is `how`.
REQUIRES: dict[str, list[tuple[str, str, str]]] = {
    "commands": [
        ("git_dirty", "mode", "present"),
        ("counts", "mode", "present"),
        ("superseded", "keeps", "present"),
    ],
    "verify": [("truncated", "output", "true"), ("cwd_is_root", "output", "true")],
    "runs": [
        ("log_prompts", "configured", "true"),
        ("mode", "run_folder", "true"),
        ("file_edits", "plan_files", "present"),
        ("edit_proposals", "plan_files", "present"),
        ("idempotent", "plan_files", "present"),
    ],
}


def _requires(
    rows: Iterable[Mapping[str, Any]], pairs: list[tuple[str, str, str]], where: str
) -> list[str]:
    return [
        f"{where}[{index}]: {inner!r} is read only inside {outer!r}, which this row lacks"
        for index, row in enumerate(rows)
        for inner, outer, how in pairs
        if inner in row and (outer not in row if how == "present" else not row.get(outer))
    ]


def _transforms(corpus: str) -> list[str]:
    top, edit = TRANSFORMS[corpus]
    key = _load(f"tests/fixtures/transforms/{corpus}/answers.yaml")
    problems = unknown(key, top, corpus)
    problems += each(key["cases"], TRANSFORM_CASE, f"{corpus}.cases")
    for case in key["cases"]:
        problems += each(case["edits"], edit, f"{corpus}.{case['file']}.edits")
    return problems


def _commands() -> list[str]:
    key = _load("tests/fixtures/commands/answers.yaml")
    problems = unknown(key, {"case", "pack", "commands", "diff", "artefacts", "cases"}, "commands")
    problems += unknown(key["diff"], {"lines", "whole", "cut", "redacted"}, "commands.diff")
    problems += each(key["cases"], {"case", "repository", "what_it_is", "git", "runs"}, "cases")
    for case in key["cases"]:
        where = f"commands.{case['case']}"
        problems += unknown(case["git"], {"init", "appended"}, f"{where}.git")
        problems += each(case["runs"], COMMANDS_RUN, f"{where}.runs")
        problems += _requires(case["runs"], REQUIRES["commands"], f"{where}.runs")
        for index, run in enumerate(case["runs"]):
            verify = run.get("verify") or {}
            problems += unknown(
                verify, {"status", "reason", "commands", "baseline"}, f"{where}[{index}].verify"
            )
            problems += unknown(
                verify.get("baseline") or {}, {"status", "commands"}, f"{where}[{index}].baseline"
            )
            problems += unknown(
                run.get("snapshots") or {}, {"before", "after"}, f"{where}[{index}].snapshots"
            )
    return problems


def _apply() -> list[str]:
    key = _load("tests/fixtures/apply/answers.yaml")
    case_keys = {"case", "what_it_is", "git", "allow_dirty", "dirty", "refused", "written", "files"}
    problems = unknown(key, {"case", "pack", "cases"}, "apply")
    problems += each(key["cases"], case_keys, "apply.cases")
    for case in key["cases"]:
        problems += unknown(
            case["git"],
            {"init", "subdirectory", "appended", "untracked", "never_added", "staged"},
            f"apply.{case['case']}.git",
        )
    return problems


def _evidence() -> list[str]:
    key = _load("tests/fixtures/evidence/answers.yaml")
    problems = unknown(key, {"case", "pack", "artefacts", "cases"}, "evidence")
    problems += each(key["cases"], {"case", "what_it_is", "git", "runs"}, "evidence.cases")
    for case in key["cases"]:
        problems += unknown(case["git"], {"init", "appended"}, f"evidence.{case['case']}.git")
        problems += each(case["runs"], EVIDENCE_RUN, f"evidence.{case['case']}.runs")
    return problems


def _verify() -> list[str]:
    key = _load("tests/fixtures/verify/answers.yaml")
    problems = unknown(key, {"cases"}, "verify")
    problems += each(key["cases"], VERIFY_CASE, "verify.cases")
    problems += _requires(key["cases"], REQUIRES["verify"], "verify.cases")
    for case in key["cases"]:
        where = f"verify.{case['case']}"
        problems += unknown(
            case["mode"], {"ci", "tty", "non_interactive", "trust_repo_config"}, f"{where}.mode"
        )
        problems += unknown(case.get("output") or {}, {"present", "absent"}, f"{where}.output")
        problems += unknown(
            case.get("baseline_result") or {},
            {"status", "reason", "commands"},
            f"{where}.baseline_result",
        )
    return problems


def _runs() -> list[str]:
    key = _load("tests/fixtures/providers/runs.yaml")
    problems = unknown(key, RUNS_TOP, "runs")
    problems += each(key["cases"], RUNS_CASE, "runs.cases")
    problems += _requires(key["cases"], REQUIRES["runs"], "runs.cases")
    for case in key["cases"]:
        where = f"runs.{case['case']}"
        problems += unknown(case.get("git") or {}, {"init", "dirty"}, f"{where}.git")
        problems += unknown(case.get("verify") or {}, {"status", "baseline"}, f"{where}.verify")
        problems += unknown(
            case.get("shows") or {},
            {"endpoint", "system_prompt", "first_message", "counts"},
            f"{where}.shows",
        )
        problems += each(
            case.get("outcomes") or [], {"index", "outcome", "word"}, f"{where}.outcomes"
        )
    for name, script in key["scripts"].items():
        problems += unknown(
            script,
            {"what_it_is", "answers", "tokens_in", "tokens_out", "closed_port"},
            f"runs.scripts.{name}",
        )
    return problems


def _scan() -> list[str]:
    paths = [
        *sorted(FIXTURES.glob("scan/*/ground_truth.yaml")),
        ROOT / "examples/gemini-legacy-app/ground_truth.yaml",
    ]
    problems: list[str] = []
    for path in paths:
        key = _load(str(path.relative_to(ROOT)))
        where = path.parent.name
        problems += unknown(key, SCAN_TOP, where)
        problems += each(key.get("findings") or [], SCAN_FINDING, f"{where}.findings")
        problems += each(key.get("bindings") or [], SCAN_BINDING, f"{where}.bindings")
        problems += each(
            key.get("must_not_report") or [],
            {"file", "line", "why", "symbol"},
            f"{where}.must_not_report",
        )
        problems += each(
            key.get("must_not_autofix") or [], {"file", "line", "why"}, f"{where}.must_not_autofix"
        )
    return problems


CORPORA: dict[str, Callable[[], list[str]]] = {
    **{corpus: functools.partial(_transforms, corpus) for corpus in TRANSFORMS},
    "commands": _commands,
    "apply": _apply,
    "evidence": _evidence,
    "verify": _verify,
    "runs": _runs,
    "scan": _scan,
}


@pytest.mark.parametrize("corpus", sorted(CORPORA))
def test_every_key_in_the_answer_key_is_one_its_oracle_reads(corpus: str) -> None:
    problems = CORPORA[corpus]()
    assert not problems, "\n".join(problems)


def test_a_misspelt_optional_key_is_caught() -> None:
    """The real keys may hold no typo, so one is planted."""
    run = {"argv": ["undo"], "exit_code": 0, "undone": []}
    assert each([run], COMMANDS_RUN, "runs") == ["runs[0]: 'undone'"]


def test_an_inner_key_without_its_outer_block_is_caught() -> None:
    rows: list[dict[str, Any]] = [{"git_dirty": True}, {"mode": "apply", "git_dirty": False}]
    assert _requires(rows, REQUIRES["commands"], "runs") == [
        "runs[0]: 'git_dirty' is read only inside 'mode', which this row lacks"
    ]
    # Present is not true: an empty `plan_files` opens its block, `run_folder: false` does not.
    cases: list[dict[str, Any]] = [
        {"plan_files": [], "file_edits": []},
        {"run_folder": False, "mode": "plan"},
    ]
    assert _requires(cases, REQUIRES["runs"], "cases") == [
        "cases[1]: 'mode' is read only inside 'run_folder', which this row lacks"
    ]
