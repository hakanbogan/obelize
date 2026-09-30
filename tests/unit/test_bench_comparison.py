"""Comparison arm: published block, calibrated tree-scan instrument, and the arm's prompt.

The tree scan must reproduce obelize's published numbers: its licence to score an arm with no plan.
"""

from __future__ import annotations

import json
import shutil
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from platforms import BENCH

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import comparison  # noqa: E402
import comparison_collect as collect  # noqa: E402
import run  # noqa: E402

pytestmark = BENCH

DOCUMENT = ROOT / "docs" / "BENCHMARK_RESULTS.md"
PROMPT = ROOT / "bench" / "COMPARISON_PROMPT.md"

# Written out: reading `comparison.ARMS` would make every both-arms assertion vacuous.
BOTH = ("obelize", "general_agent")

# Kinds that can realise a key row; `text_mention` is the scanner's name for the key's `dynamic`.
KINDS = {
    "import",
    "call",
    "method_call",
    "attribute",
    "dynamic",
    "text_mention",
    "manifest",
    "star_import",
}

# Kinds that are a usage or a pin, not a sentence.
USAGE = {"import", "call", "method_call", "attribute", "manifest"}

# Round one's development split, copied from `bench/cases.yaml` and `bench/results/round-1/`.
DEV_CASES = 13
DEV_ROWS = 174
OBELIZE_MIGRATED = 17
AGENT_MIGRATED = 154

# The one `manual`-capped case the other arm cleared; a computed value would agree with anything.
MANUAL_CEILING_CLEARED = "LucasHJin__vit"

# The two edits the review rejected, as `case: file`.
REJECTED = {
    "Arnav3241__Jarvis-v13": "Chat/response.py",
    "humanbound__humanbound-firewall": "src/humanbound_firewall/llm/gemini.py",
}

# Words only this repository knows; `genai` and `google-generativeai` are the job, so allowed.
FORBIDDEN = (
    "obelize",
    "benchmark",
    "ground truth",
    "answer key",
    "call_sites",
    "needs_review",
    "file_not_fully_migrated",
    "cases.yaml",
)


def state_once() -> comparison.Comparison:
    return comparison.load()


def a_case(identifier: str, **over: Any) -> run.Case:
    fields: dict[str, Any] = {
        "id": identifier,
        "origin": "corpus",
        "control": False,
        "split": "dev",
        "repo": "https://example.invalid/r",
        "sha": "0" * 40,
        "python": "cpython-3.12.9-macos-aarch64-none",
        "from_version": "0.8.6",
        "to_version": "2.24.0",
        "install": (),
        "test_cmd": None,
        "ground_truth": {"call_sites": [], "manifests": [], "tests_cover_change": False},
        "review": {},
        "source": None,
    }
    fields.update(over)
    return run.Case(**fields)


def a_site(path: str, line: int, symbol: str, kind: str = "call") -> dict[str, Any]:
    return {"path": path, "line": line, "kind": kind, "symbol": symbol, "label": "auto"}


def a_finding(path: str, line: int, symbol: str, kind: str = "call") -> list[Any]:
    return [path, line, kind, symbol]


def measured(**over: Any) -> dict[str, Any]:
    table: dict[str, Any] = {
        "unmigrated": 0,
        "patch_compiles": True,
        "runtime_seconds": 1.0,
        "tests_baseline": {"status": "not_run", "passed": None, "failed": None, "skipped": None},
        "tests_after": {"status": "not_run", "passed": None, "failed": None, "skipped": None},
    }
    table.update(over)
    return table


def a_comparison(
    cases: list[run.Case],
    record: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    published: dict[str, Any] | None = None,
) -> comparison.Comparison:
    return comparison.Comparison(
        1,
        cases,
        {"cases": record or {}, "guide": {"url": "u", "fetched_at": "t", "sha256_text": "d" * 64}},
        review or {},
        published or {case.id: {"tier": "x", "measurements": measured()} for case in cases},
    )


def a_record(
    base: list[list[Any]],
    agent: list[list[Any]],
    obelize: list[list[Any]] | None = None,
    **over: Any,
) -> dict[str, Any]:
    per_case: dict[str, Any] = {
        "slug": "0" * 8,
        "started_at": 100,
        "finished_at": 130,
        "runtime_seconds": 30,
        "changes": [{"path": "app.py", "status": "M", "added": 2, "removed": 2}],
        "obelize_changes": [{"path": "app.py", "status": "M", "added": 1, "removed": 1}],
        "written": ["app.py"],
        "compiles": True,
        "missing_key_files": [],
        "findings": {"base": base, "general_agent": agent, "obelize": obelize or base},
        "repeat": None,
        "tests_after": None,
    }
    per_case.update(over)
    return per_case


def reviewed(**wrong: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "reviews": {
            arm: {case: {"reviewed": "read", "wrong": rows} for case, rows in wrong.items()}
            for arm in BOTH
        }
    }


def test_the_block_in_the_document_is_what_the_generator_renders() -> None:
    assert comparison.main(["--check"]) == 0


def test_the_generator_prints_the_block_when_it_is_not_checking(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert comparison.main([]) == 0
    assert "| Arm | Cases |" in capsys.readouterr().out


def test_a_stale_document_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(comparison, "render", lambda state: "something else")
    assert comparison.main(["--check"]) == 1


def test_a_document_with_no_markers_is_refused() -> None:
    with pytest.raises(SystemExit):
        comparison.block("nothing here")


def test_the_development_split_is_the_cases_the_round_ran() -> None:
    state = comparison.load()
    assert len(comparison.dev(state)) == DEV_CASES
    assert {case.split for case in comparison.dev(state)} == {"dev"}


def test_the_key_rows_are_the_ones_this_file_pins() -> None:
    state = comparison.load()
    assert sum(comparison.rows(case) for case in comparison.dev(state)) == DEV_ROWS


def test_obelize_cleared_is_what_the_round_published_case_by_case() -> None:
    """Calibration: the tree scan must equal the round's plan-and-withheld count, case by case."""
    state = comparison.load()
    for case in comparison.dev(state):
        assert sum(comparison.cleared(state, case, "obelize").values()) == (
            comparison.published_migrated(state, case)
        ), case.id


def test_obelize_cleared_in_total_is_the_rounds_own_number() -> None:
    state = comparison.load()
    assert comparison.totals(state, "obelize")["cleared"] == OBELIZE_MIGRATED


def test_the_reduced_ladder_returns_the_tier_the_round_published() -> None:
    """Dropping the two scan-report rungs costs nothing on this split."""
    state = comparison.load()
    for case in comparison.dev(state):
        assert comparison.tier(state, case, "obelize") == state.published[case.id]["tier"], case.id


def test_every_case_in_the_split_has_a_ceiling_and_the_ceiling_caps_obelize() -> None:
    """A ceiling is computed from the key, and for a rule it is binding."""
    state = comparison.load()
    for case in comparison.dev(state):
        assert run.ceiling(case) is not None, case.id
    assert comparison.totals(state, "obelize")["verified_success"] == 0


def test_a_case_capped_only_by_a_manual_row_is_not_capped_for_the_other_arm() -> None:
    """`manual` distrusts a rule, not every edit (ADR-045 D7); `no test command` caps both arms."""
    state = comparison.load()
    verified = [
        case
        for case in comparison.dev(state)
        if comparison.tier(state, case, "general_agent") == "verified_success"
    ]
    assert [case.id for case in verified] == [MANUAL_CEILING_CLEARED]
    assert run.ceiling(verified[0]) == "a row the key marks `manual`"
    for case in comparison.dev(state):
        if run.ceiling(case) == "no test command":
            for arm in BOTH:
                assert comparison.tier(state, case, arm) != "verified_success", (case.id, arm)


def test_the_agent_cleared_the_number_this_file_pins() -> None:
    assert comparison.totals(state_once(), "general_agent")["cleared"] == AGENT_MIGRATED


def test_the_review_rejected_exactly_these_edits() -> None:
    state = state_once()
    found = {
        case.id: row["path"]
        for case in comparison.dev(state)
        for arm in BOTH
        for row in comparison.wrong_edits(state, case, arm)
    }
    assert found == REJECTED


def test_no_arm_introduced_a_legacy_usage_that_was_not_there() -> None:
    state = comparison.load()
    for case in comparison.dev(state):
        for arm in BOTH:
            assert comparison.introduced(state, case, arm) == 0, (case.id, arm)


def test_no_arm_deleted_a_file_the_key_names_a_row_in() -> None:
    state = comparison.load()
    for case in comparison.dev(state):
        assert state.record["cases"][case.id]["missing_key_files"] == [], case.id


def test_a_cell_survives_an_edit_that_moves_every_line() -> None:
    case = a_case("c", ground_truth={"call_sites": [a_site("app.py", 9, "g.configure")]})
    state = a_comparison(
        [case],
        {"c": a_record([a_finding("app.py", 9, "g.configure")], [])},
        reviewed(c=[]),
    )
    moved = a_comparison(
        [case],
        {
            "c": a_record(
                [a_finding("app.py", 9, "g.configure")],
                [a_finding("app.py", 44, "g.configure")],
            )
        },
        reviewed(c=[]),
    )
    assert sum(comparison.cleared(state, case, "general_agent").values()) == 1
    assert sum(comparison.cleared(moved, case, "general_agent").values()) == 0


def test_a_row_the_scan_never_saw_is_credited_to_neither_arm() -> None:
    case = a_case("c", ground_truth={"call_sites": [a_site("app.py", 9, "g.configure")]})
    state = a_comparison([case], {"c": a_record([], [])}, reviewed(c=[]))
    assert sum(comparison.visible(state, case).values()) == 0
    assert sum(comparison.cleared(state, case, "general_agent").values()) == 0
    assert comparison.left(state, case, "general_agent") == 1


def test_clearing_more_than_the_key_names_is_capped_at_what_it_names() -> None:
    """Two usages on one cell, one key row: removing both still clears one."""
    case = a_case("c", ground_truth={"call_sites": [a_site("app.py", 9, "g.configure")]})
    state = a_comparison(
        [case],
        {
            "c": a_record(
                [a_finding("app.py", 9, "g.configure"), a_finding("app.py", 20, "g.configure")],
                [],
            )
        },
        reviewed(c=[]),
    )
    assert sum(comparison.cleared(state, case, "general_agent").values()) == 1


def test_a_new_legacy_usage_is_not_netted_off_a_removal() -> None:
    case = a_case("c", ground_truth={"call_sites": [a_site("app.py", 9, "g.configure")]})
    state = a_comparison(
        [case],
        {
            "c": a_record(
                [a_finding("app.py", 9, "g.configure")],
                [a_finding("other.py", 2, "g.configure")],
            )
        },
        reviewed(c=[]),
    )
    assert sum(comparison.cleared(state, case, "general_agent").values()) == 1
    assert comparison.introduced(state, case, "general_agent") == 1
    assert comparison.tier(state, case, "general_agent") == "wrong"


def test_a_manifest_row_is_matched_as_the_kind_the_scan_gives_a_pin() -> None:
    case = a_case(
        "c",
        ground_truth={
            "manifests": [{"path": "requirements.txt", "line": 3, "symbol": "google-generativeai"}]
        },
    )
    state = a_comparison(
        [case],
        {
            "c": a_record(
                [a_finding("requirements.txt", 3, "google-generativeai", "manifest")],
                [],
            )
        },
        reviewed(c=[]),
    )
    assert sum(comparison.cleared(state, case, "general_agent").values()) == 1


def test_a_sentence_naming_the_old_sdk_is_not_a_new_usage_of_it() -> None:
    case = a_case("c", ground_truth={"call_sites": [a_site("app.py", 9, "g.configure")]})
    state = a_comparison(
        [case],
        {
            "c": a_record(
                [a_finding("app.py", 9, "g.configure")],
                [a_finding("CHANGELOG.md", 4, "google.generativeai", "text_mention")],
            )
        },
        reviewed(c=[]),
    )
    assert sum(comparison.cleared(state, case, "general_agent").values()) == 1
    assert comparison.introduced(state, case, "general_agent") == 0
    assert comparison.tier(state, case, "general_agent") == "patched_unverified"


def test_a_parse_error_is_not_a_cell() -> None:
    """Its symbol is an excerpt of somebody's source, which is not a symbol."""
    assert comparison.scan_cells([a_finding("a.py", 1, "def f(:", "parse_error")]) == Counter()


def test_the_kinds_are_the_ones_this_file_writes_out() -> None:
    assert set(comparison.ROW_KINDS) == KINDS
    assert set(comparison.USAGE_KINDS) == USAGE
    assert set(comparison.USAGE_KINDS) < set(comparison.ROW_KINDS)


def test_corrections_are_rows_left_plus_edits_the_review_rejected() -> None:
    case = a_case(
        "c",
        ground_truth={
            "call_sites": [a_site("app.py", 9, "g.configure"), a_site("app.py", 20, "g.Model")]
        },
    )
    state = a_comparison(
        [case],
        {
            "c": a_record(
                [a_finding("app.py", 9, "g.configure"), a_finding("app.py", 20, "g.Model")],
                [a_finding("app.py", 20, "g.Model")],
            )
        },
        reviewed(c=[{"path": "app.py", "line": 9, "why": "wrote the wrong client"}]),
    )
    assert comparison.left(state, case, "general_agent") == 1
    assert comparison.human_edits(state, case, "general_agent") == 2


def test_patch_correct_is_null_when_the_arm_wrote_nothing() -> None:
    case = a_case("c")
    state = a_comparison([case], {"c": a_record([], [], changes=[])}, reviewed(c=[]))
    assert comparison.patch_correct(state, case, "general_agent") is None
    assert comparison.tier(state, case, "general_agent") == "unsupported"


def test_an_edit_the_review_rejected_makes_the_case_wrong() -> None:
    case = a_case("c")
    state = a_comparison(
        [case], {"c": a_record([], [])}, reviewed(c=[{"path": "app.py", "line": 1, "why": "no"}])
    )
    assert comparison.patch_correct(state, case, "general_agent") is False
    assert comparison.tier(state, case, "general_agent") == "wrong"


def test_a_case_with_no_review_is_refused() -> None:
    case = a_case("c")
    state = a_comparison([case], {"c": a_record([], [])}, {"reviews": {}})
    with pytest.raises(SystemExit):
        comparison.review(state, case, "general_agent")


def test_every_case_in_the_split_has_a_review_for_every_arm() -> None:
    state = comparison.load()
    for case in comparison.dev(state):
        for arm in BOTH:
            assert comparison.review(state, case, arm)["reviewed"], (case.id, arm)


def test_no_review_names_a_case_or_an_arm_the_comparison_does_not_hold() -> None:
    state = comparison.load()
    known = {case.id for case in comparison.dev(state)}
    written = state.review["reviews"]
    assert set(written) == set(BOTH)
    for arm in written:
        assert set(written[arm]) == known, arm


def test_a_rejected_edit_names_a_file_the_arm_actually_changed() -> None:
    state = comparison.load()
    for case in comparison.dev(state):
        for arm in BOTH:
            touched = {str(change["path"]) for change in comparison.changes(state, case, arm)}
            for row in comparison.wrong_edits(state, case, arm):
                assert str(row["path"]) in touched, (case.id, arm, row["path"])
                assert row["why"], (case.id, arm, row["path"])


def test_the_reviewer_and_the_round_are_recorded() -> None:
    state = comparison.load()
    assert state.review["round"] == state.number
    assert state.review["reviewer"]
    assert state.review["reviewed_at"]


def test_the_prompt_names_nothing_only_this_repository_knows() -> None:
    text = PROMPT.read_text(encoding="utf-8").lower()
    head = text.split("-->", 1)[1] if text.startswith("<!--") else text
    for word in FORBIDDEN:
        assert word not in head, word


def test_the_rendered_prompt_drops_the_note_that_names_this_repository(tmp_path: Path) -> None:
    """The file's leading comment names `obelize`; the arm may not read it."""
    rendered = collect.rendered(tmp_path / "t", tmp_path / "g.txt", tmp_path / "m")
    assert PROMPT.read_text(encoding="utf-8").startswith("<!--")
    assert not rendered.startswith("<!--")
    assert "obelize" not in rendered.split("\n\n")[0].lower()


def test_two_cases_are_handed_the_same_text_apart_from_their_paths(tmp_path: Path) -> None:
    one = collect.rendered(tmp_path / "a", tmp_path / "g.txt", tmp_path / "ma")
    two = collect.rendered(tmp_path / "b", tmp_path / "g.txt", tmp_path / "mb")
    assert one != two
    assert one.replace(str(tmp_path / "a"), "T").replace(str(tmp_path / "ma"), "M") == (
        two.replace(str(tmp_path / "b"), "T").replace(str(tmp_path / "mb"), "M")
    )


def test_a_prompt_with_no_slot_to_substitute_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "prompt.md"
    empty.write_text("nothing to fill in\n", encoding="utf-8")
    monkeypatch.setattr(collect, "PROMPT", empty)
    with pytest.raises(SystemExit):
        collect.rendered(tmp_path, tmp_path, tmp_path)


def test_the_slug_is_a_digest_of_the_case_id_and_carries_no_name() -> None:
    assert collect.slug("owner__repo") == collect.slug("owner__repo")
    assert collect.slug("owner__repo") != collect.slug("owner__other")
    assert len(collect.slug("owner__repo")) == 8
    assert "owner" not in collect.slug("owner__repo")


def test_every_slug_in_the_record_is_the_digest_of_its_case_id() -> None:
    state = comparison.load()
    for case in comparison.dev(state):
        assert state.record["cases"][case.id]["slug"] == collect.slug(case.id), case.id


class Fake:
    """Records every command; answers those a rule matches."""

    def __init__(self, rules: list[tuple[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.rules = list(rules or [])

    def __call__(self, argv: Any, cwd: Any, env: Any, timeout_s: int) -> run.Completed:
        self.calls.append(tuple(argv))
        for needle, answer in self.rules:
            if needle in " ".join(str(part) for part in argv):
                found: run.Completed = answer(tuple(argv), Path(cwd))
                return found
        return run.Completed(tuple(argv), 0, 0.0, False, "")

    def names(self) -> list[str]:
        return [" ".join(call) for call in self.calls]


def says(code: int = 0, out: str = "") -> Any:
    def answer(argv: tuple[str, ...], cwd: Path) -> run.Completed:
        return run.Completed(argv, code, 0.0, False, out)

    return answer


def makes_a_repo(argv: tuple[str, ...], cwd: Path) -> run.Completed:
    """`git init`, faked down to the one directory `_exclude` writes into."""
    Path(argv[2], ".git", "info").mkdir(parents=True, exist_ok=True)
    return run.Completed(argv, 0, 0.0, False, "")


def scans(rows: list[dict[str, Any]] | None = None, folders: int = 1) -> Any:
    def answer(argv: tuple[str, ...], cwd: Path) -> run.Completed:
        tree = Path(argv[argv.index("--repo") + 1])
        for index in range(folders):
            folder = tree / ".obelize" / "runs" / f"2026092{index}T000000Z-abcdef12"
            folder.mkdir(parents=True)
            (folder / "findings.json").write_text(json.dumps({"findings": rows or []}))
        return run.Completed(argv, 0, 0.0, False, "")

    return answer


def a_tree(root: Path, sha: str = "0" * 40) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".git" / "info").mkdir(parents=True, exist_ok=True)
    return root


def prepared(work: Path, case_id: str = "c", sha: str = "0" * 40) -> str:
    """A work root shaped the way `prepare` leaves one."""
    name = collect.slug(case_id)
    a_tree(work / "agent" / name, sha)
    a_tree(work / "base" / name, sha)
    guide = work / "guide"
    guide.mkdir(parents=True, exist_ok=True)
    (guide / "guide.html").write_bytes(b"<p>x</p>")
    (guide / "guide.txt").write_text("x\n", encoding="utf-8")
    meta = work / "meta" / name
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "started").write_text("100")
    (meta / "finished").write_text("160")
    (meta / "prompt.md").write_text(
        collect.rendered(work / "agent" / name, guide / "guide.txt", meta), encoding="utf-8"
    )
    (work / "order.json").write_text(
        json.dumps(
            {
                "guide": {
                    "url": collect.GUIDE_URL,
                    "fetched_at": "t",
                    "sha256_html": collect.digest(b"<p>x</p>"),
                    "sha256_text": collect.digest(b"x\n"),
                },
                "order": {name: {"case": case_id}},
                "prepared_at": "t",
            }
        )
    )
    return name


def only(case: run.Case, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collect, "dev_cases", lambda: [case])


def test_a_work_root_that_already_holds_something_is_refused(tmp_path: Path) -> None:
    (tmp_path / "already").mkdir()
    with pytest.raises(SystemExit, match="not empty"):
        collect.prepare(tmp_path, execute=Fake(), fetch=lambda url: b"x", env={}, at="t")


def test_a_work_root_under_somebody_elses_configuration_is_refused(tmp_path: Path) -> None:
    """A nested work tree silently inherits the parent's pytest, ruff and coverage (ADR-043 D1)."""
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    with pytest.raises(SystemExit, match="not isolated"):
        collect.prepare(tmp_path / "w", execute=Fake(), fetch=lambda url: b"x", env={}, at="t")


def test_a_guide_that_comes_back_empty_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no guide"):
        collect.prepare(tmp_path / "w", execute=Fake(), fetch=lambda url: b"", env={}, at="t")


def test_a_fetch_that_fails_stops_the_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    only(a_case("c"), monkeypatch)
    execute = Fake([("--depth", says(128))])
    with pytest.raises(SystemExit, match="fetch failed"):
        collect.prepare(tmp_path / "w", execute=execute, fetch=lambda url: b"x", env={}, at="t")


def test_preparing_leaves_two_identical_trees_and_one_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = a_case("c")
    only(case, monkeypatch)
    work = tmp_path / "w"
    execute = Fake([("git -C", makes_a_repo)])
    document = collect.prepare(
        work, execute=execute, fetch=lambda url: b"<p>hi</p>", env={}, at="2026-09-22T00:00:00Z"
    )
    name = collect.slug("c")
    assert set(document["order"]) == {name}
    assert (work / "agent" / name / ".git").is_dir()
    assert (work / "base" / name / ".git").is_dir()
    assert (work / "meta" / name / "prompt.md").is_file()
    assert document["guide"]["sha256_html"] == collect.digest(b"<p>hi</p>")


def test_a_split_with_no_development_cases_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "corpus", list)
    with pytest.raises(SystemExit, match="no development-split"):
        collect.dev_cases()


def test_the_development_split_the_collector_reads_is_the_case_files() -> None:
    assert {case.id for case in collect.dev_cases()} == {
        case.id for case in run.corpus() if case.split == "dev"
    }


def test_nothing_prepared_here_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="nothing prepared"):
        collect._order(tmp_path)


def test_a_guide_whose_bytes_changed_since_preparing_is_refused(tmp_path: Path) -> None:
    prepared(tmp_path)
    (tmp_path / "guide" / "guide.txt").write_text("edited\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="prepared as"):
        collect._order(tmp_path)


def test_a_case_with_no_tree_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = a_case("c")
    only(case, monkeypatch)
    prepared(tmp_path)
    shutil.rmtree(tmp_path / "agent" / collect.slug("c"))
    with pytest.raises(SystemExit, match="not prepared"):
        collect._case_record(case, tmp_path, 1, execute=Fake(), env={})


def test_a_tree_that_is_not_at_the_pinned_commit_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = a_case("c")
    only(case, monkeypatch)
    prepared(tmp_path)
    execute = Fake([("rev-parse", says(0, "f" * 40))])
    with pytest.raises(SystemExit, match="pinned"):
        collect._case_record(case, tmp_path, 1, execute=execute, env={})


def test_a_git_command_that_fails_names_what_was_asked(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="rev-parse failed"):
        collect.head(tmp_path, execute=Fake([("rev-parse", says(128))]), env={})


def test_a_prompt_that_is_not_the_committed_one_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = a_case("c")
    only(case, monkeypatch)
    name = prepared(tmp_path)
    (tmp_path / "meta" / name / "prompt.md").write_text("migrate it, and also...", "utf-8")
    execute = Fake([("rev-parse", says(0, "0" * 40))])
    with pytest.raises(SystemExit, match=r"not COMPARISON_PROMPT\.md"):
        collect._case_record(case, tmp_path, 1, execute=execute, env={})


def test_a_case_with_no_finish_stamp_is_refused(tmp_path: Path) -> None:
    meta = tmp_path / "m"
    meta.mkdir()
    (meta / "started").write_text("100")
    with pytest.raises(SystemExit, match="no finished stamp"):
        collect.timings(meta)


def test_a_finish_stamp_before_its_start_is_refused(tmp_path: Path) -> None:
    meta = tmp_path / "m"
    meta.mkdir()
    (meta / "started").write_text("200")
    (meta / "finished").write_text("100")
    with pytest.raises(SystemExit, match="before its start"):
        collect.timings(meta)


def test_a_scan_that_fails_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="scan exited"):
        collect.findings(a_tree(tmp_path / "t"), execute=Fake([("scan", says(2))]), env={})


def test_a_tree_with_two_run_folders_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="found 2"):
        collect.findings(a_tree(tmp_path / "t"), execute=Fake([("scan", scans(folders=2))]), env={})


def test_a_scan_leaves_no_run_folder_behind(tmp_path: Path) -> None:
    tree = a_tree(tmp_path / "t")
    rows = [{"path": "app.py", "line": 3, "kind": "call", "symbol": "g.configure"}]
    found = collect.findings(tree, execute=Fake([("scan", scans(rows))]), env={})
    assert found == [["app.py", 3, "call", "g.configure"]]
    assert not (tree / ".obelize").exists()


def test_a_round_whose_work_tree_is_gone_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="work tree is gone"):
        collect._obelize_tree(tmp_path, "abc", tmp_path / "nowhere")


def test_the_obelize_copy_drops_its_evidence_and_its_venv(tmp_path: Path) -> None:
    source = a_tree(tmp_path / "round" / "case")
    (source / "app.py").write_text("x\n")
    (source / ".obelize" / "runs").mkdir(parents=True)
    (source / ".venv").mkdir()
    copy = collect._obelize_tree(tmp_path / "w", "abc", source)
    assert (copy / "app.py").is_file()
    assert not (copy / ".obelize").exists()
    assert not (copy / ".venv").exists()
    assert collect._obelize_tree(tmp_path / "w", "abc", source) == copy


def test_a_repeat_of_a_case_outside_the_split_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="not a development-split case"):
        collect.repeat(tmp_path, ["not-a-case"])


def test_a_repeat_with_nothing_prepared_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    only(a_case("c"), monkeypatch)
    with pytest.raises(SystemExit, match="nothing prepared"):
        collect.repeat(tmp_path, ["c"])


def test_a_repeat_staged_twice_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    only(a_case("c"), monkeypatch)
    prepared(tmp_path)
    assert collect.repeat(tmp_path, ["c"]) == [collect.slug("c")]
    with pytest.raises(SystemExit, match="already staged"):
        collect.repeat(tmp_path, ["c"])


def test_a_repeat_whose_prompt_is_not_the_committed_one_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = a_case("c")
    only(case, monkeypatch)
    name = prepared(tmp_path)
    collect.repeat(tmp_path, ["c"])
    (tmp_path / "repeat-meta" / name / "prompt.md").write_text("different", encoding="utf-8")
    with pytest.raises(SystemExit, match="repeat's prompt"):
        collect._repeat_record(case, tmp_path, name, execute=Fake(), env={})


def test_a_case_that_was_not_run_twice_has_no_repeat(tmp_path: Path) -> None:
    assert collect._repeat_record(a_case("c"), tmp_path, "abc", execute=Fake(), env={}) is None


def test_a_venv_that_cannot_be_built_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="uv venv exited"):
        collect._venv(tmp_path / "v", a_case("c"), execute=Fake([("uv venv", says(1))]), env={})


def test_a_venv_that_is_already_there_is_not_built_again(tmp_path: Path) -> None:
    venv = tmp_path / "v"
    venv.mkdir()
    execute = Fake()
    assert collect._venv(venv, a_case("c"), execute=execute, env={}) == venv / "bin" / "python"
    assert execute.calls == []


def test_only_the_python_files_the_arm_wrote_are_compiled() -> None:
    changed = [
        {"path": "app.py", "status": "M"},
        {"path": "gone.py", "status": "D"},
        {"path": "README.md", "status": "M"},
    ]
    assert collect.written(changed) == ["app.py"]


def test_an_arm_that_wrote_no_python_is_not_asked_whether_it_compiles(tmp_path: Path) -> None:
    assert collect.compiles(tmp_path, [], Path("python"), execute=Fake(), env={}) is None


def test_a_compile_failure_is_recorded_and_not_raised(tmp_path: Path) -> None:
    execute = Fake([("-c", says(1))])
    assert collect.compiles(tmp_path, ["a.py"], Path("python"), execute=execute, env={}) is False


def test_a_binary_file_has_no_line_counts() -> None:
    assert collect._numstat("-\t-\tlogo.png\0") == [("logo.png", (None, None))]
    assert collect._numstat("3\t1\tapp.py\0") == [("app.py", (3, 1))]


def test_a_file_the_arm_deleted_is_a_delete(tmp_path: Path) -> None:
    execute = Fake(
        [
            ("--numstat", says(0, "0\t4\tgone.py\0")),
            ("--name-status", says(0, "D\0gone.py\0")),
        ]
    )
    assert collect.changes(tmp_path, execute=execute, env={}) == [
        {"path": "gone.py", "status": "D", "added": 0, "removed": 4}
    ]


def test_a_file_the_key_names_that_the_arm_removed_is_named(tmp_path: Path) -> None:
    case = a_case("c", ground_truth={"call_sites": [a_site("app.py", 1, "g.configure")]})
    assert collect.missing_key_files(case, tmp_path) == ["app.py"]
    (tmp_path / "app.py").write_text("x\n")
    assert collect.missing_key_files(case, tmp_path) == []


def test_the_after_suite_is_run_and_its_pin_is_read_back(tmp_path: Path) -> None:
    case = a_case("c", install=("uv pip install pytest",), test_cmd="python -m pytest -q")
    execute = Fake([("importlib.metadata", says(0, "2.24.0\n"))])
    found = collect.suite(
        case,
        tmp_path,
        Path("python"),
        tmp_path / "j.xml",
        execute=execute,
        env={},
    )
    assert found["status"] == "pass"
    assert found["sdk_to"] == "2.24.0"
    assert any("uv pip install pytest" in name for name in execute.names())
    assert any("--junitxml" in name for name in execute.names())


def test_an_install_that_fails_stops_the_case(tmp_path: Path) -> None:
    case = a_case("c", install=("uv pip install pytest",), test_cmd="python -m pytest -q")
    execute = Fake([("uv pip install", says(1))])
    with pytest.raises(SystemExit, match=r"install .uv pip install pytest. exited"):
        collect.suite(case, tmp_path, Path("p"), tmp_path / "j", execute=execute, env={})


def test_a_pin_that_fails_to_install_stops_the_case(tmp_path: Path) -> None:
    case = a_case("c", test_cmd="python -m pytest -q")
    execute = Fake([("google-genai==", says(1))])
    with pytest.raises(SystemExit, match="pinning google-genai exited"):
        collect.suite(case, tmp_path, Path("p"), tmp_path / "j", execute=execute, env={})


def test_a_pin_that_installs_something_else_stops_the_case(tmp_path: Path) -> None:
    case = a_case("c", test_cmd="python -m pytest -q")
    execute = Fake([("importlib.metadata", says(0, "1.0.0\n"))])
    with pytest.raises(SystemExit, match=r"installed 1\.0\.0"):
        collect.suite(case, tmp_path, Path("p"), tmp_path / "j", execute=execute, env={})


def test_the_guide_is_converted_by_a_rule_that_keeps_a_code_sample(tmp_path: Path) -> None:
    page = (
        b"<html><head><style>p{color:red}</style></head><body>"
        b"<p>Before</p><pre><code><span>import</span><span> </span>"
        b"<span>google.generativeai</span></code></pre>"
        b"<script>window.x=1</script></body></html>"
    )
    text = collect.as_text(page)
    assert "import google.generativeai" in text
    assert "color:red" not in text
    assert "window.x" not in text
    assert "Before" in text


def test_the_guide_snapshot_records_both_digests(tmp_path: Path) -> None:
    snapshot = collect.guide(tmp_path, lambda url: b"<p>hi</p>", "2026-09-22T00:00:00Z")
    assert snapshot["sha256_html"] == collect.digest(b"<p>hi</p>")
    assert snapshot["bytes_text"] == len((tmp_path / "guide" / "guide.txt").read_bytes())
    assert snapshot["url"] == collect.GUIDE_URL


def test_the_guide_is_downloaded_from_the_url_the_protocol_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    class Response:
        def read(self) -> bytes:
            return b"page"

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def urlopen(url: str, timeout: int) -> Response:
        asked.append(url)
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert collect.download(collect.GUIDE_URL) == b"page"
    assert asked == [collect.GUIDE_URL]


def test_a_case_that_was_not_run_twice_has_no_divergence() -> None:
    case = a_case("c")
    state = a_comparison([case], {"c": a_record([], [])}, reviewed(c=[]))
    assert comparison.divergence(state, case) is None


def test_a_second_run_that_went_somewhere_else_is_reported() -> None:
    case = a_case("c", ground_truth={"call_sites": [a_site("app.py", 9, "g.configure")]})
    again = {
        "started_at": 0,
        "finished_at": 40,
        "runtime_seconds": 40,
        "changes": [{"path": "app.py", "status": "M", "added": 9, "removed": 2}],
        "findings": [a_finding("app.py", 9, "g.configure")],
    }
    state = a_comparison(
        [case],
        {"c": a_record([a_finding("app.py", 9, "g.configure")], [], repeat=again)},
        reviewed(c=[]),
    )
    found = comparison.divergence(state, case)
    assert found is not None
    assert found["same_files"] is True
    assert found["same_shape"] is False
    assert (found["cleared"], found["cleared_again"]) == (1, 0)


def test_an_off_key_file_is_reported_and_is_not_a_verdict() -> None:
    case = a_case("c", ground_truth={"call_sites": [a_site("app.py", 9, "g.configure")]})
    state = a_comparison(
        [case],
        {
            "c": a_record(
                [a_finding("app.py", 9, "g.configure")],
                [],
                changes=[
                    {"path": "app.py", "status": "M", "added": 1, "removed": 1},
                    {"path": "README.md", "status": "M", "added": 1, "removed": 1},
                ],
            )
        },
        reviewed(c=[]),
    )
    assert comparison.off_key(state, case, "general_agent") == ["README.md"]
    assert comparison.tier(state, case, "general_agent") == "patched_unverified"


def test_a_suite_that_regressed_is_wrong() -> None:
    case = a_case("c", ground_truth={"call_sites": [], "tests_cover_change": True})
    passing = {"status": "pass", "passed": 3, "failed": 0, "skipped": 0}
    failing = {"status": "fail", "passed": 1, "failed": 2, "skipped": 0}
    state = a_comparison(
        [case],
        {"c": a_record([], [], tests_after=failing)},
        reviewed(c=[]),
        {"c": {"tier": "x", "measurements": measured(tests_baseline=passing)}},
    )
    assert comparison.baseline(state, case)["status"] == "pass"
    assert comparison.suite(state, case, "general_agent")["status"] == "fail"
    assert comparison.tier(state, case, "general_agent") == "wrong"


def test_a_regression_is_not_blamed_on_an_arm_that_wrote_nothing() -> None:
    """On an untouched tree the after-run measures only the SDK swap."""
    case = a_case("c", ground_truth={"call_sites": [], "tests_cover_change": True})
    passing = {"status": "pass", "passed": 3, "failed": 0, "skipped": 0}
    failing = {"status": "fail", "passed": 0, "failed": 1, "skipped": 0}
    state = a_comparison(
        [case],
        {"c": a_record([], [], changes=[], tests_after=failing)},
        reviewed(c=[]),
        {"c": {"tier": "x", "measurements": measured(tests_baseline=passing)}},
    )
    assert comparison.tier(state, case, "general_agent") == "unsupported"


def test_an_after_suite_that_cannot_import_its_module_is_a_failure(tmp_path: Path) -> None:
    """A collection error (`errors="1"`, exit 2) counts as one failure."""
    case = a_case("c", test_cmd="python -m pytest -q")
    junit = tmp_path / "j.xml"

    def broken(argv: tuple[str, ...], cwd: Path) -> run.Completed:
        junit.write_text(
            '<testsuites><testsuite errors="1" failures="0" skipped="0" tests="1"/></testsuites>',
            encoding="utf-8",
        )
        return run.Completed(argv, 2, 0.0, False, "")

    execute = Fake([("importlib.metadata", says(0, "2.24.0\n")), ("--junitxml", broken)])
    found = collect.suite(case, tmp_path, Path("python"), junit, execute=execute, env={})
    assert (found["status"], found["failed"]) == ("fail", 1)


def test_a_complete_migration_with_a_passing_suite_is_verified() -> None:
    case = a_case("c", ground_truth={"call_sites": [], "tests_cover_change": True})
    passing = {"status": "pass", "passed": 3, "failed": 0, "skipped": 0}
    state = a_comparison(
        [case],
        {"c": a_record([], [], tests_after=passing)},
        reviewed(c=[]),
        {"c": {"tier": "x", "measurements": measured(tests_baseline=passing)}},
    )
    assert comparison.tier(state, case, "general_agent") == "verified_success"


def test_an_arm_that_did_not_compile_is_wrong() -> None:
    case = a_case("c")
    state = a_comparison([case], {"c": a_record([], [], compiles=False)}, reviewed(c=[]))
    assert comparison.compiles(state, case, "general_agent") is False
    assert comparison.tier(state, case, "general_agent") == "wrong"


def test_an_arm_with_no_after_phase_did_not_run_one() -> None:
    case = a_case("c")
    state = a_comparison([case], {"c": a_record([], [])}, reviewed(c=[]))
    assert comparison.suite(state, case, "general_agent")["status"] == "not_run"


def test_obelize_s_numbers_come_from_the_round_and_not_from_the_record() -> None:
    case = a_case("c")
    state = a_comparison(
        [case],
        {
            "c": a_record(
                [],
                [],
                compiles=False,
                runtime_seconds=999,
                tests_after={"status": "skipped_here", "passed": 1, "failed": 0, "skipped": 0},
            )
        },
        reviewed(c=[]),
        {"c": {"tier": "x", "measurements": measured(patch_compiles=True, runtime_seconds=2.5)}},
    )
    assert comparison.compiles(state, case, "obelize") is True
    assert comparison.runtime(state, case, "obelize") == 2.5
    assert comparison.runtime(state, case, "general_agent") == 999
    assert comparison.suite(state, case, "obelize")["status"] == "not_run"
    assert comparison.suite(state, case, "general_agent")["status"] == "skipped_here"


def test_a_round_with_no_collected_record_says_so() -> None:
    assert "Not run" in comparison.render(a_comparison([]))
    state = comparison.load(99)
    assert state.record == {"cases": {}}
    assert comparison.dev(state) == []


def test_a_share_of_nothing_is_not_a_percentage() -> None:
    assert comparison._share(0, 0) == "--"
    assert comparison._share(1, 4) == "25.0%"


def test_a_long_run_is_printed_in_minutes() -> None:
    assert comparison._seconds(2.0) == "2.0s"
    assert comparison._seconds(120.0) == "2.0m"


def test_a_table_with_nothing_in_it_says_what_it_found(monkeypatch: pytest.MonkeyPatch) -> None:
    case = a_case("c")
    record = a_record([], [], changes=[], obelize_changes=[])
    state = a_comparison([case], {"c": record}, reviewed(c=[]))
    assert "Neither arm wrote outside the key" in "\n".join(comparison._off_key_table(state))
    assert "No case was run twice" in "\n".join(comparison._repeat_table(state))


def test_preparing_from_the_command_line_uses_the_round_the_case_file_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    only(a_case("c"), monkeypatch)
    monkeypatch.setattr(run, "shell", Fake([("git -C", makes_a_repo)]))
    monkeypatch.setattr(collect, "download", lambda url: b"<p>hi</p>")
    work = tmp_path / "w"
    assert collect.main(["prepare", "--work", str(work), "--at", "2026-01-01T00:00:00Z"]) == 0
    assert "1 cases prepared" in capsys.readouterr().out
    assert json.loads((work / "order.json").read_text())["prepared_at"] == "2026-01-01T00:00:00Z"


def test_preparing_stamps_the_moment_when_none_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    only(a_case("c"), monkeypatch)
    monkeypatch.setattr(run, "shell", Fake([("git -C", makes_a_repo)]))
    monkeypatch.setattr(collect, "download", lambda url: b"<p>hi</p>")
    work = tmp_path / "w"
    assert collect.main(["prepare", "--work", str(work)]) == 0
    stamped = json.loads((work / "order.json").read_text())["prepared_at"]
    assert stamped.endswith("Z")
    assert stamped[:2] == "20"


def test_staging_a_repeat_from_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    only(a_case("c"), monkeypatch)
    prepared(tmp_path)
    assert collect.main(["repeat", "--work", str(tmp_path), "--case", "c"]) == 0
    assert "1 cases staged" in capsys.readouterr().out


def test_recording_writes_the_file_the_scorer_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    case = a_case("c", ground_truth={"call_sites": [a_site("app.py", 9, "g.configure")]})
    only(case, monkeypatch)
    work = tmp_path / "w"
    prepared(work)
    a_tree(tmp_path / "round-1" / "c")
    monkeypatch.setattr(run, "WORK", tmp_path)
    monkeypatch.setattr(collect, "RESULTS", tmp_path / "out")
    rows = [{"path": "app.py", "line": 9, "kind": "call", "symbol": "g.configure"}]
    monkeypatch.setattr(
        run,
        "shell",
        Fake([("rev-parse", says(0, "0" * 40)), ("scan", scans(rows))]),
    )
    assert collect.main(["record", "--work", str(work), "--round", "1"]) == 0
    assert "1 cases" in capsys.readouterr().out
    written = json.loads((tmp_path / "out" / "round-1.json").read_text())
    assert written["round"] == 1
    assert written["arms"] == ["general_agent", "obelize"]
    assert written["cases"]["c"]["runtime_seconds"] == 60


def test_a_collected_record_carries_no_line_of_anybody_elses_source() -> None:
    record = json.loads(
        (ROOT / "bench" / "results" / "comparison" / "round-1.json").read_text(encoding="utf-8")
    )
    for per_case in record["cases"].values():
        for rows in per_case["findings"].values():
            for row in rows:
                assert len(row) == 4
                assert isinstance(row[1], int)
        for change in per_case["changes"] + per_case["obelize_changes"]:
            assert set(change) == {"path", "status", "added", "removed"}


def test_the_record_names_the_guide_it_was_run_against() -> None:
    state = comparison.load()
    guide = state.record["guide"]
    assert guide["url"] == collect.GUIDE_URL
    assert len(guide["sha256_text"]) == 64
    assert guide["fetched_at"].endswith("Z")


def test_a_second_run_is_read_back_beside_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = a_case("c")
    only(case, monkeypatch)
    name = prepared(tmp_path)
    collect.repeat(tmp_path, ["c"])
    meta = tmp_path / "repeat-meta" / name
    (meta / "started").write_text("200")
    (meta / "finished").write_text("245")
    rows = [{"path": "app.py", "line": 3, "kind": "call", "symbol": "g.configure"}]
    execute = Fake([("scan", scans(rows))])
    again = collect._repeat_record(case, tmp_path, name, execute=execute, env={})
    assert again is not None
    assert again["runtime_seconds"] == 45
    assert again["findings"] == [["app.py", 3, "call", "g.configure"]]


def test_a_round_checkout_that_is_not_at_the_pinned_commit_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = a_case("c")
    only(case, monkeypatch)
    work = tmp_path / "w"
    prepared(work)
    a_tree(tmp_path / "round-1" / "c")
    monkeypatch.setattr(run, "WORK", tmp_path)

    def elsewhere(argv: tuple[str, ...], cwd: Path) -> run.Completed:
        at = "f" * 40 if "/obelize/" in " ".join(argv) else "0" * 40
        return run.Completed(argv, 0, 0.0, False, at)

    execute = Fake([("rev-parse", elsewhere), ("scan", scans())])
    with pytest.raises(SystemExit, match="round's checkout is not at"):
        collect._case_record(case, work, 1, execute=execute, env={})


def test_a_suite_that_does_not_cover_the_change_does_not_verify() -> None:
    case = a_case("c", ground_truth={"call_sites": [], "tests_cover_change": False})
    passing = {"status": "pass", "passed": 3, "failed": 0, "skipped": 0}
    state = a_comparison(
        [case],
        {"c": a_record([], [], tests_after=passing)},
        reviewed(c=[]),
        {"c": {"tier": "x", "measurements": measured(tests_baseline=passing)}},
    )
    assert comparison.tier(state, case, "general_agent") == "patched_unverified"


def test_a_suite_that_collected_nothing_does_not_verify() -> None:
    case = a_case("c", ground_truth={"call_sites": [], "tests_cover_change": True})
    empty = {"status": "pass", "passed": 0, "failed": 0, "skipped": 4}
    state = a_comparison(
        [case],
        {"c": a_record([], [], tests_after=empty)},
        reviewed(c=[]),
        {"c": {"tier": "x", "measurements": measured(tests_baseline=empty)}},
    )
    assert comparison.tier(state, case, "general_agent") == "patched_unverified"


def test_each_arm_is_counted_from_its_own_diff() -> None:
    state = state_once()
    case = next(c for c in comparison.dev(state) if c.id == "humanbound__humanbound-firewall")
    assert len(comparison.changes(state, case, "obelize")) == 0
    assert len(comparison.changes(state, case, "general_agent")) == 5


def test_a_file_the_arm_created_is_staged_before_it_is_counted(tmp_path: Path) -> None:
    """An untracked new file is invisible to the diff, so `git add -A` runs first."""
    execute = Fake(
        [
            ("--numstat", says(0, "7\t0\tnew.py\0")),
            ("--name-status", says(0, "A\0new.py\0")),
        ]
    )
    found = collect.changes(tmp_path, execute=execute, env={})
    assert found == [{"path": "new.py", "status": "A", "added": 7, "removed": 0}]
    assert any(name.endswith("add -A") for name in execute.names())


def test_a_repeat_starts_from_the_tree_the_first_run_never_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    only(a_case("c"), monkeypatch)
    name = prepared(tmp_path)
    (tmp_path / "agent" / name / "edited-by-the-first-run.py").write_text("x\n")
    collect.repeat(tmp_path, ["c"])
    assert not (tmp_path / "repeat" / name / "edited-by-the-first-run.py").exists()


def test_a_round_named_on_the_command_line_is_the_one_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = a_case("c")
    only(case, monkeypatch)
    work = tmp_path / "w"
    prepared(work)
    a_tree(tmp_path / "round-2" / "c")
    monkeypatch.setattr(run, "WORK", tmp_path)
    monkeypatch.setattr(collect, "RESULTS", tmp_path / "out")
    monkeypatch.setattr(
        run,
        "shell",
        Fake([("rev-parse", says(0, "0" * 40)), ("scan", scans())]),
    )
    assert collect.main(["record", "--work", str(work), "--round", "2"]) == 0
    assert (tmp_path / "out" / "round-2.json").is_file()
    assert json.loads((tmp_path / "out" / "round-2.json").read_text())["round"] == 2


def test_a_key_row_the_scan_only_partly_sees_is_credited_once() -> None:
    """Two rows in one cell, one of them reported: one row is observable."""
    case = a_case(
        "c",
        ground_truth={
            "call_sites": [a_site("app.py", 9, "g.configure"), a_site("app.py", 20, "g.configure")]
        },
    )
    state = a_comparison(
        [case], {"c": a_record([a_finding("app.py", 9, "g.configure")], [])}, reviewed(c=[])
    )
    assert sum(comparison.visible(state, case).values()) == 1
    assert sum(comparison.cleared(state, case, "general_agent").values()) == 1
    assert comparison.left(state, case, "general_agent") == 1


def test_a_cell_that_grew_clears_nothing() -> None:
    """A grown cell clears zero, not a negative count; the growth is `introduced`."""
    case = a_case("c", ground_truth={"call_sites": [a_site("app.py", 9, "g.configure")]})
    state = a_comparison(
        [case],
        {
            "c": a_record(
                [a_finding("app.py", 9, "g.configure")],
                [a_finding("app.py", 9, "g.configure"), a_finding("app.py", 30, "g.configure")],
            )
        },
        reviewed(c=[]),
    )
    assert comparison.cleared(state, case, "general_agent") == Counter()
    assert comparison.left(state, case, "general_agent") == 1
    assert comparison.introduced(state, case, "general_agent") == 1


def test_a_usage_count_that_only_fell_is_not_a_negative_introduction() -> None:
    case = a_case("c", ground_truth={"call_sites": [a_site("app.py", 9, "g.configure")]})
    state = a_comparison(
        [case],
        {
            "c": a_record(
                [a_finding("app.py", 9, "g.configure"), a_finding("app.py", 20, "g.configure")],
                [a_finding("app.py", 9, "g.configure")],
            )
        },
        reviewed(c=[]),
    )
    assert comparison.introduced(state, case, "general_agent") == 0


def test_a_suite_that_was_already_failing_did_not_regress() -> None:
    case = a_case("c", ground_truth={"call_sites": [], "tests_cover_change": True})
    failing = {"status": "fail", "passed": 1, "failed": 2, "skipped": 0}
    state = a_comparison(
        [case],
        {"c": a_record([], [], tests_after=failing)},
        reviewed(c=[]),
        {"c": {"tier": "x", "measurements": measured(tests_baseline=failing)}},
    )
    assert comparison.tier(state, case, "general_agent") == "patched_unverified"


def test_one_row_left_is_partial() -> None:
    case = a_case(
        "c",
        ground_truth={
            "call_sites": [a_site("app.py", 9, "g.configure"), a_site("app.py", 20, "g.Model")]
        },
    )
    state = a_comparison(
        [case],
        {
            "c": a_record(
                [a_finding("app.py", 9, "g.configure"), a_finding("app.py", 20, "g.Model")],
                [a_finding("app.py", 20, "g.Model")],
            )
        },
        reviewed(c=[]),
    )
    assert comparison.left(state, case, "general_agent") == 1
    assert comparison.tier(state, case, "general_agent") == "partial"


def test_a_suite_that_never_ran_does_not_verify() -> None:
    """`not_run` is not `pass`, and eleven of thirteen cases are that."""
    case = a_case("c", ground_truth={"call_sites": [], "tests_cover_change": True})
    state = a_comparison([case], {"c": a_record([], [])}, reviewed(c=[]))
    assert comparison.suite(state, case, "general_agent")["status"] == "not_run"
    assert comparison.tier(state, case, "general_agent") == "patched_unverified"
