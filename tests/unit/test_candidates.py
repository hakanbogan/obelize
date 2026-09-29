"""`bench/CANDIDATES.md`: selector arithmetic, the committed rows against ADR-040, staleness."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

from platforms import BENCH

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

import candidates  # noqa: E402 -- the path insert above is what makes this importable

pytestmark = BENCH

FRAME = yaml.safe_load(candidates.FRAME.read_text(encoding="utf-8"))
FRAME_SCAN = json.loads(candidates.FRAME_SCAN.read_text(encoding="utf-8"))
CORPUS = candidates.load()
ROWS: list[dict[str, Any]] = CORPUS.data["candidates"]
CHANGES = [surface.change for surface in CORPUS.surfaces]

# Owners the rules were written against; a benchmark over them measures itself.
DEVELOPMENT = frozenset({"eli64s", "llegomark", "log2timeline"})


def finding(**overrides: Any) -> dict[str, Any]:
    """One finding, with only the fields the selector reads."""
    row = {
        "path": "app.py",
        "line": 1,
        "kind": "call",
        "symbol": "google.generativeai.configure",
        "scan_status": "eligible",
        "confidence_reason": "alias_resolved",
    }
    row.update(overrides)
    return row


def row(**overrides: Any) -> dict[str, Any]:
    """One candidate row, with every field the renderer reads."""
    entry = {
        "full_name": "owner/repo",
        "owner": "owner",
        "url": "https://github.com/owner/repo",
        "sha": "a" * 40,
        "license": "MIT",
        "fork": False,
        "archived": False,
        "pushed_at": "2026-01-01T00:00:00Z",
        "stars": 1,
        "size_kb": 10,
        "source": "frame",
        "tests": {"test_files": "tests/test_app.py"},
    }
    entry.update(overrides)
    return entry


def corpus(
    rows: list[dict[str, Any]],
    findings: dict[str, list[dict[str, Any]]] | None = None,
    scanned: dict[str, list[dict[str, Any]]] | None = None,
    **data: Any,
) -> candidates.Corpus:
    found = findings or {}
    body: dict[str, Any] = {
        "drawn_at": "2026-09-21T00:00:00Z",
        "frame": {
            "sample": "bench/gate1/sample.yaml",
            "scan": "bench/results/gate1/scan.json",
            "queried_at": "2026-09-18T14:05:55Z",
            "repositories": 80,
            "licensed": 34,
        },
        "instrument": {"obelize_version": "0.1.0", "pack": "gemini/p", "pack_sha256": "0" * 64},
        "max_per_owner": 2,
        "candidates": rows,
        "rejected": [],
        "surfaces": [],
    }
    body.update(data)
    resolved = {entry["change"] for entry in body["surfaces"]}
    body["surfaces"] = [
        *body["surfaces"],
        *(
            {
                "change": change,
                "query": "q",
                "hits": 0,
                "examined": 0,
                "outcome": "absent",
                "drawn": None,
                "skipped": [],
            }
            for change in CHANGES
            if change not in resolved
        ),
    ]
    records = {
        entry["full_name"]: {
            "full_name": entry["full_name"],
            "sha": entry["sha"],
            "counts": {"eligible": 0, "findings": len(found.get(entry["full_name"], []))},
            "findings": found.get(entry["full_name"], []),
        }
        for entry in rows
    }
    for name, rows_for in (scanned or {}).items():
        records[name] = {
            "full_name": name,
            "sha": "c" * 40,
            "counts": {"eligible": 0, "findings": len(rows_for)},
            "findings": rows_for,
        }
    return candidates.Corpus(data=body, records=records, surfaces=candidates.surfaces())


def surface(change: str) -> candidates.Surface:
    return next(one for one in CORPUS.surfaces if one.change == change)


def test_every_change_in_the_pack_is_a_surface_exactly_once() -> None:
    assert len(CHANGES) == len(set(CHANGES))
    assert "manifest-dependency" in CHANGES
    assert "embed-content" in CHANGES


def test_a_surface_carries_the_legacy_names_its_own_parameters_state() -> None:
    """Each of the pack's six change kinds names its symbols in a different place."""
    assert surface("rename-import").symbols == (
        "google.generativeai",
        "google.generativeai.types",
    )
    assert surface("configure-to-client").symbols == ("google.generativeai.configure",)
    assert surface("embed-content").symbols == ("google.generativeai.embed_content",)
    assert surface("manifest-dependency").symbols == ("google-generativeai",)
    assert "google.generativeai.GenerativeModel.generate_content" in (
        surface("generative-model-calls").symbols
    )
    assert "google.generativeai.types.FunctionDeclaration" in (
        surface("flag-function-calling-types").symbols
    )
    assert "google.generativeai.ChatSession.history" in (
        surface("flag-removed-object-attributes").symbols
    )


def test_the_one_change_that_names_patterns_carries_them_instead_of_symbols() -> None:
    indirect = surface("flag-legacy-module-reached-indirectly")
    assert indirect.symbols == ()
    assert indirect.patterns == ("dynamic_access", "mock_patch_target", "sys_modules_stub")


def test_a_surface_is_exercised_by_a_symbol_or_by_a_pattern_and_by_nothing_else() -> None:
    embed = surface("embed-content")
    indirect = surface("flag-legacy-module-reached-indirectly")
    assert candidates.exercises([finding(symbol="google.generativeai.embed_content")], embed)
    assert not candidates.exercises([finding()], embed)
    assert candidates.exercises(
        [finding(symbol="google.generativeai", confidence_reason="mock_patch_target")], indirect
    )
    assert not candidates.exercises([finding()], indirect)


@pytest.mark.parametrize(
    "path",
    ["package/google/generativeai/files.py", "google/generativeai/__init__.py"],
)
def test_a_repository_that_carries_the_sdks_own_source_is_not_using_it(path: str) -> None:
    assert candidates.vendors([finding(path=path)])


@pytest.mark.parametrize("path", ["app.py", "google/genai/client.py", "src/generativeai.py"])
def test_a_file_that_merely_mentions_the_package_is_not_the_package(path: str) -> None:
    assert not candidates.vendors([finding(path=path)])


def test_the_pattern_key_is_the_call_sites_and_not_the_pin_or_the_readme() -> None:
    """A manifest row is a pin and a mention is a sentence; neither is a usage."""
    assert candidates.pattern_key(
        [
            finding(symbol="b"),
            finding(symbol="a"),
            finding(symbol="a", line=9),
            finding(symbol="google-generativeai", kind="manifest"),
            finding(symbol="c", kind="text_mention"),
        ]
    ) == ("a", "b")


def test_test_evidence_names_the_first_path_that_showed_each_word() -> None:
    found = candidates.evidence(
        [
            "src/app.py",
            "requirements.txt",
            "tests/test_app.py",
            "tests/test_other.py",
            "conftest.py",
            ".github/workflows/ci.yml",
            "pyproject.toml",
        ]
    )
    assert list(found) == list(candidates.EVIDENCE)
    assert found["test_files"] == "tests/test_app.py"
    assert found["manifest"] == "requirements.txt"
    assert found["ci_workflow"] == ".github/workflows/ci.yml"
    assert found["test_config"] == "conftest.py"


@pytest.mark.parametrize(
    "path",
    ["src/test_app.py", "app_test.py", "app/tests/unit/thing.py", "test/helpers.py"],
)
def test_a_python_test_file_is_recognised_under_either_convention(path: str) -> None:
    assert candidates.evidence([path]) == {"test_files": path}


@pytest.mark.parametrize("path", ["src/app.py", "docs/testing.md", "tests/data.json"])
def test_a_file_that_is_not_a_test_is_not_evidence_of_one(path: str) -> None:
    assert "test_files" not in candidates.evidence([path])


@pytest.mark.parametrize(
    "path",
    [".github/dependabot.yml", ".github/ISSUE_TEMPLATE/bug.md", ".github/workflows/deep/ci.yml"],
)
def test_only_a_workflow_is_a_workflow(path: str) -> None:
    """GitHub reads only `.github/workflows/*.yml`, not nested directories."""
    assert "ci_workflow" not in candidates.evidence([path])


def test_a_short_sha_is_a_prefix_and_not_a_pin() -> None:
    """GitHub resolves a prefix against whatever the repository holds that day."""
    assert candidates.FULL_SHA.match("a" * 40)
    assert not candidates.FULL_SHA.match("a" * 7)
    assert not candidates.FULL_SHA.match("A" * 40)


def test_the_two_words_that_are_not_a_licence_are_both_refused() -> None:
    """`NOASSERTION` is GitHub saying it found a licence file it could not identify."""
    assert set(candidates.UNLICENSED) == {"none", "NOASSERTION"}
    table = candidates._rule_table(corpus([row(license="NOASSERTION")]))
    assert table[2].endswith("| **no** |")


def test_nothing_in_a_file_list_is_nothing() -> None:
    assert candidates.evidence(["README.md", "src/app.py"]) == {}


def test_the_rules_table_reports_a_corpus_that_breaks_a_rule() -> None:
    twenty = [row(full_name=f"o{index}/r", owner=f"o{index}") for index in range(20)]
    good = candidates._rule_table(corpus(twenty))
    assert all(line.endswith("| yes |") for line in good[2:])
    bad = candidates._rule_table(
        corpus(
            [
                row(fork=True, sha="a" * 7),
                row(full_name="owner/two"),
                row(full_name="owner/three"),
            ]
        )
    )
    assert sum(line.endswith("| **no** |") for line in bad[2:]) == 4


def test_the_rules_table_says_no_when_a_row_pins_a_sha_no_scan_record_holds() -> None:
    """The one rule a well-formed row can still break: the SHA moved under it."""
    mismatched = corpus([row()])
    mismatched.records["owner/repo"]["sha"] = "b" * 40
    table = candidates._rule_table(mismatched)
    assert table[5] == "| Every row has a scan record at the SHA it pins | **no** |"


def test_a_surface_nothing_exercises_is_rendered_from_its_query() -> None:
    drawn = {
        "change": "list-files",
        "query": "generativeai list_files language:python",
        "hits": 10,
        "examined": 3,
        "outcome": "no_eligible_result",
        "drawn": None,
        "skipped": [],
    }
    one = corpus(
        [row()],
        {"owner/repo": [finding(symbol="google.generativeai.embed_content")]},
        surfaces=[drawn],
    )
    table = "\n".join(candidates._surface_table(one))
    assert "| `embed-content` | 1 | 1 | exercised by 1, first `owner/repo` |" in table
    assert "| `list-files` | 1 | 0 | no eligible result, 10 hit(s) searched |" in table
    assert "| `list-files` | `generativeai list_files language:python` | 10 | 3 |" in (
        "\n".join(candidates._query_table(one))
    )


def test_the_query_table_says_why_the_results_it_passed_over_were_passed_over() -> None:
    drawn = {
        "change": "embed-content",
        "query": "q",
        "hits": 10,
        "examined": 3,
        "outcome": "no_eligible_result",
        "drawn": None,
        "skipped": [
            {"full_name": "a/b", "reason": "unlicensed"},
            {"full_name": "c/d", "reason": "unlicensed"},
            {"full_name": "e/f", "reason": "vendors_the_sdk"},
        ],
    }
    table = "\n".join(candidates._query_table(corpus([row()], surfaces=[drawn])))
    assert "| 2 unlicensed; 1 vendors_the_sdk |" in table


def test_a_repository_that_declares_the_new_sdk_on_its_own_line_is_named() -> None:
    one = corpus(
        [row()],
        {
            "owner/repo": [
                finding(symbol="google-genai", kind="manifest", path="requirements.txt", line=9)
            ]
        },
    )
    text = candidates.render(one)
    assert "1 of the 1 repositories scanned declare the new distribution" in text
    assert "trap: `owner/repo`." in text


def test_a_google_genai_row_at_a_legacy_pin_is_the_proposed_add_and_not_a_declaration() -> None:
    """The row `manifest-dependency` would write is not one the repository wrote (ADR-041 D2)."""
    pin = {"kind": "manifest", "path": "requirements.txt", "line": 4}
    one = corpus(
        [row()],
        {
            "owner/repo": [
                finding(symbol="google-generativeai", **pin),
                finding(symbol="google-genai", **pin),
            ]
        },
    )
    assert candidates.declares_the_new_sdk(one) == []
    assert candidates.proposes_the_new_sdk(one) == ["owner/repo"]
    text = candidates.render(one)
    assert "None of the 1 repositories scanned declares the new distribution" in text
    assert "proposes to **add**" in text


def test_a_drawn_row_is_named_in_the_query_table() -> None:
    drawn = {
        "change": "embed-content",
        "query": "q",
        "hits": 10,
        "examined": 1,
        "outcome": "drawn",
        "drawn": "other/repo",
        "skipped": [],
    }
    table = "\n".join(candidates._query_table(corpus([row()], surfaces=[drawn])))
    assert "`drawn` | `other/repo` |" in table


def test_a_legacy_name_no_change_names_is_listed_and_the_named_ones_are_not() -> None:
    one = corpus(
        [row()],
        {
            "owner/repo": [
                finding(symbol="google.generativeai.ChatCompletion"),
                finding(symbol="google.generativeai.ChatCompletion", line=2),
                finding(symbol="google.generativeai.configure"),
                finding(symbol="google-genai", kind="manifest"),
            ]
        },
    )
    table = "\n".join(candidates._unnamed_table(one))
    assert "| `google.generativeai.ChatCompletion` | 1 | 2 |" in table
    assert "configure" not in table
    assert "google-genai" not in table


def test_the_rejection_table_lists_every_reason_including_the_ones_nothing_hit() -> None:
    table = "\n".join(
        candidates._rejection_table(
            corpus([row()], rejected=[{"full_name": "a/b", "reason": "fork"}])
        )
    )
    assert "| `fork` | 1 |" in table
    assert "| `unlicensed` | 0 |" in table
    for reason in candidates.REASONS:
        assert f"| `{reason}` |" in table


def test_the_evidence_table_counts_the_words_and_keeps_their_order() -> None:
    table = candidates._evidence_table(
        corpus([row(), row(full_name="o2/r", owner="o2", tests={"manifest": "setup.py"})])
    )
    assert table[2:] == [
        "| `test_files` | 1 |",
        "| `test_config` | 0 |",
        "| `ci_workflow` | 0 |",
        "| `manifest` | 1 |",
    ]


def test_a_candidate_with_no_test_evidence_prints_a_dash() -> None:
    table = "\n".join(candidates._candidate_table(corpus([row(tests={})])))
    assert "| -- | frame |" in table


def test_block_refuses_a_document_with_no_markers() -> None:
    with pytest.raises(SystemExit, match="no candidates block"):
        candidates.block("# nothing here\n")


def test_the_block_is_what_the_document_holds() -> None:
    begin, end = candidates.MARKERS
    assert candidates.block(f"prose\n{begin}\ninside\n{end}\nmore prose\n") == "inside"


def test_the_published_document_is_what_the_selector_renders_today() -> None:
    published = candidates.block(candidates.DOCUMENT.read_text(encoding="utf-8"))
    assert published == candidates.render(CORPUS)


def test_the_command_prints_the_block_and_checks_the_document(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert candidates.main([]) == 0
    assert "candidates, drawn" in capsys.readouterr().out
    assert candidates.main(["--check"]) == 0
    stale = tmp_path / "CANDIDATES.md"
    begin, end = candidates.MARKERS
    stale.write_text(f"{begin}\nnot the table\n{end}\n", encoding="utf-8")
    monkeypatch.setattr(candidates, "DOCUMENT", stale)
    assert candidates.main(["--check"]) == 1
    assert "is stale" in capsys.readouterr().out


def test_there_are_at_least_twenty_candidates() -> None:
    assert len(ROWS) >= 20


@pytest.mark.parametrize("field", ["full_name", "owner", "url", "sha", "license", "source"])
def test_every_candidate_carries_the_fields_the_criterion_names(field: str) -> None:
    assert all(entry[field] for entry in ROWS)


def test_every_sha_is_a_full_one() -> None:
    assert all(candidates.FULL_SHA.match(entry["sha"]) for entry in ROWS)


def test_every_licence_is_an_spdx_identifier() -> None:
    assert not [entry for entry in ROWS if entry["license"] in candidates.UNLICENSED]


def test_the_url_and_the_owner_are_the_repository_and_not_something_typed() -> None:
    for entry in ROWS:
        owner, _, name = entry["full_name"].partition("/")
        assert entry["owner"] == owner
        assert entry["url"] == f"https://github.com/{owner}/{name}"


def test_no_candidate_is_a_fork_and_no_owner_has_more_than_two() -> None:
    assert not [entry for entry in ROWS if entry["fork"]]
    counted = Counter(entry["owner"] for entry in ROWS)
    assert max(counted.values()) <= candidates.MAX_PER_OWNER


def test_no_candidate_belongs_to_a_development_corpus_owner() -> None:
    assert not [entry for entry in ROWS if entry["owner"] in DEVELOPMENT]


def test_every_candidate_has_a_scan_record_at_the_sha_it_pins() -> None:
    for entry in ROWS:
        record = CORPUS.records[entry["full_name"]]
        assert record["sha"] == entry["sha"]
        assert record["findings"], f"{entry['full_name']} has no finding"


def test_the_two_scan_records_do_not_hold_the_same_repository_twice() -> None:
    drawn = json.loads(candidates.DRAWN_SCAN.read_text(encoding="utf-8"))["scanned"]
    frame = {record["full_name"] for record in FRAME_SCAN["scanned"]}
    assert not frame & {record["full_name"] for record in drawn}


def test_the_frame_is_partitioned_into_candidates_and_published_rejections() -> None:
    frame = {entry["full_name"] for entry in FRAME["repositories"]}
    kept = {entry["full_name"] for entry in ROWS if entry["source"] == "frame"}
    rejected = {entry["full_name"] for entry in CORPUS.data["rejected"]}
    assert kept | rejected == frame
    assert not kept & rejected


def test_every_rejection_and_every_skip_names_a_reason_from_the_closed_set() -> None:
    assert {entry["reason"] for entry in CORPUS.data["rejected"]} <= set(candidates.REASONS)
    skipped = {entry["reason"] for drawn in CORPUS.data["surfaces"] for entry in drawn["skipped"]}
    assert skipped <= set(candidates.SKIP_REASONS)


def test_every_unexercised_surface_is_resolved_and_every_resolved_one_was_unexercised() -> None:
    """ADR-040 D5: a surface with no candidate behind it is never left silent."""
    unexercised = {
        one.change
        for one in CORPUS.surfaces
        if not any(
            candidates.exercises(candidates.found(CORPUS, entry["full_name"]), one)
            for entry in ROWS
        )
    }
    resolved = {drawn["change"] for drawn in CORPUS.data["surfaces"]}
    assert unexercised <= resolved
    assert resolved <= set(CHANGES)


def test_each_query_records_an_outcome_its_own_count_supports() -> None:
    for drawn in CORPUS.data["surfaces"]:
        assert drawn["outcome"] in candidates.OUTCOMES
        assert drawn["query"]
        if drawn["outcome"] == "absent":
            assert drawn["hits"] == 0
            assert drawn["drawn"] is None
        elif drawn["outcome"] == "no_eligible_result":
            assert drawn["hits"] > 0
            assert drawn["drawn"] is None
        else:
            assert drawn["drawn"] in {entry["full_name"] for entry in ROWS}


def test_a_drawn_candidate_says_which_surface_drew_it_and_really_exercises_it() -> None:
    for entry in ROWS:
        if entry["source"] == "frame":
            continue
        change = entry["source"].removeprefix("surface:")
        assert change in CHANGES
        assert candidates.exercises(candidates.found(CORPUS, entry["full_name"]), surface(change))


def test_what_declares_the_new_sdk_is_read_off_the_scans() -> None:
    """Computed, not stored: a derived list in a data file can disagree with its source."""
    declared = set(candidates.declares_the_new_sdk(CORPUS))
    for name, record in CORPUS.records.items():
        own = {
            (found["path"], found["line"])
            for found in record["findings"]
            if found["kind"] == "manifest" and found["symbol"] == "google-genai"
        } - {
            (found["path"], found["line"])
            for found in record["findings"]
            if found["kind"] == "manifest" and found["symbol"] == "google-generativeai"
        }
        assert (name in declared) is bool(own)


def test_only_a_manifest_row_can_be_a_declaration() -> None:
    """A `text_mention` carrying the distribution name is a sentence, not a pin."""
    one = corpus(
        [row()],
        {"owner/repo": [finding(symbol="google-genai", kind="text_mention", line=3)]},
    )
    assert candidates.declares_the_new_sdk(one) == []
    assert candidates.proposes_the_new_sdk(one) == []


def test_every_google_genai_row_in_the_corpus_is_a_proposed_add() -> None:
    """All seven sit on a legacy pin, so the corpus lacks the trap `docs/BENCHMARK.md` names."""
    assert candidates.declares_the_new_sdk(CORPUS) == []
    assert len(candidates.proposes_the_new_sdk(CORPUS)) == 7


def test_no_candidate_vendors_the_legacy_sdk() -> None:
    """A case on the library's own source would measure migrating the library."""
    assert not [
        entry for entry in ROWS if candidates.vendors(candidates.found(CORPUS, entry["full_name"]))
    ]


def test_every_test_witness_is_a_path_that_shows_that_word() -> None:
    for entry in ROWS:
        assert set(entry["tests"]) <= set(candidates.EVIDENCE)
        for word, path in entry["tests"].items():
            assert candidates.evidence([path]).get(word) == path


def test_the_document_publishes_every_candidate_url_and_full_sha() -> None:
    published = candidates.DOCUMENT.read_text(encoding="utf-8")
    for entry in ROWS:
        assert entry["url"] in published
        assert entry["sha"] in published
        assert entry["license"] in published
        assert entry["owner"] in published


def test_the_document_links_the_decision_that_says_what_a_candidate_is() -> None:
    published = candidates.DOCUMENT.read_text(encoding="utf-8")
    assert "ADR-040" in published
    assert re.search(r"\[ADR-040\]\(\.\./docs/adr/ADR-040-[^)]+\.md\)", published)
