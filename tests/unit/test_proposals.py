"""The model pass where the corpus cannot reach: the `write_refused` race and caller refusals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from obelize import fsutil
from obelize.models import Edit, EditProposal, ImpactPlan, ManifestPlan, ModelConfig
from obelize.providers import base, guard, proposals
from obelize.providers import openai_compat as adapter
from obelize.transforms import codemod

BEFORE = b"import google.generativeai as genai\n\nmodel = genai.GenerativeModel('x')\n"
AFTER = b"from google import genai\n\nmodel = genai.Client().models\n"

SETTINGS = ModelConfig(
    provider="openai_compat",
    base_url="http://localhost:11434/v1",
    model="qwen2.5-coder",
)


def consultation(path: str = "a.py", line: int = 3) -> base.Consultation:
    return base.Consultation(
        context=base.Context(path=path, start_line=1, end_line=3, text=BEFORE.decode("utf-8")),
        line=line,
        column=0,
        symbol="google.generativeai.GenerativeModel",
        bail="generation_config_not_static",
        pack_id="gemini/google-generativeai-to-google-genai",
        to_package="google-genai",
        to_modules=("google.genai",),
        limitations=(),
    )


def proposal(path: str = "a.py", line: int = 3) -> EditProposal:
    return EditProposal(
        path=path,
        start_line=line,
        end_line=line,
        symbol="google.generativeai.GenerativeModel",
        replacement="model = genai.Client().models",
        rationale="the client is constructed where the model was",
    )


def decided(
    index: int = 1, path: str = "a.py", line: int = 3, *, after: bytes = AFTER
) -> proposals.Decided:
    one = consultation(path, line)
    return proposals.Decided(
        asked=proposals.Asked(index, one, b'{"messages": []}'),
        reply=base.Reply(proposal(path, line), 10, 2),
        checked=guard.Checked(proposal(path, line), None, "in range", after),
    )


def session(*rows: proposals.Decided) -> proposals.Session:
    return proposals.Session(SETTINGS, rows, (), proposals.placement(rows))


def outcome(one: proposals.Session, **flags: object) -> list[str]:
    return [row.outcome for row in proposals.records(one, **flags)]  # type: ignore[arg-type]


def test_an_accepted_proposal_the_apply_refused_is_not_recorded_as_written() -> None:
    """A file can change between `fsutil.gate` and `fsutil.apply`, which is the authority."""
    one = session(decided())
    refused = fsutil.Apply(refused=(fsutil.Refused(path="a.py", reason="missing"),))
    assert outcome(one, applied=refused, apply=True, accept=True) == ["write_refused"]
    written = fsutil.Apply(
        written=(fsutil.Written(path="a.py", before_sha256="a" * 64, after_sha256="b" * 64),)
    )
    assert outcome(one, applied=written, apply=True, accept=True) == ["written"]


def test_the_flags_are_asked_before_the_placement() -> None:
    """A run that would write nothing does not say which of two proposals holds the file."""
    two = session(decided(1), decided(2, line=3))
    assert outcome(two, apply=False, accept=False) == ["not_applied", "not_applied"]
    assert outcome(two, apply=True, accept=False) == ["not_accepted", "not_accepted"]
    nothing = fsutil.Apply()
    assert outcome(two, applied=nothing, apply=True, accept=True) == [
        "write_refused",
        "file_already_proposed",
    ]


def test_one_file_takes_one_proposal_and_the_first_one_holds_it() -> None:
    """ADR-039 D5: a guard checks a whole file, so two proposals for one are two files."""
    rows = (decided(1), decided(2), decided(3, path="b.py"))
    placed = proposals.placement(rows)
    assert [(one.index, one.path) for one in placed] == [(1, "a.py"), (3, "b.py")]
    assert proposals.Session(SETTINGS, rows, (), placed).numbers == {"a.py": (1,), "b.py": (3,)}


def test_a_refused_proposal_holds_no_file() -> None:
    one = proposals.Decided(
        asked=proposals.Asked(1, consultation(), b"{}"),
        reply=base.Reply(proposal(), 1, 1),
        checked=guard.Checked(proposal(), "path_outside_root", "it climbs out"),
    )
    assert proposals.placement([one]) == ()
    assert outcome(session(one), apply=True, accept=True) == ["guard_refused"]


def test_the_plan_holds_a_proposal_the_flags_would_not_write() -> None:
    """A dry run must show the model's diff, or nobody can decide on `--accept-model`."""
    one = session(decided())
    model = fsutil.Change(path="a.py", before=BEFORE, after=AFTER)
    # Rewritten by the pack rules, which no model flag may hold back.
    rules = fsutil.Change(path="b.py", before=BEFORE, after=AFTER)
    changes = [model, rules]
    assert proposals.writable(changes, one, apply=True, accept=True) == (model, rules)
    assert proposals.writable(changes, one, apply=True, accept=False) == (rules,)
    assert proposals.writable(changes, one, apply=False, accept=False) == (rules,)


def outcome_of(run: codemod.Run, path: str) -> codemod.Outcome:
    return next(one for one in run.files if one.path == path)


def driver(after: bytes = BEFORE) -> codemod.Run:
    """A one-file run the rules left alone, which is every consulted file."""
    return codemod.Run(
        files=(
            codemod.Outcome(
                path="a.py",
                before=BEFORE,
                after=after,
                edits=(
                    Edit(
                        path="a.py",
                        line=3,
                        status="needs_review",
                        rule_id="generative-model-calls",
                        reason="generation_config_not_static",
                    ),
                    Edit(
                        path="a.py",
                        line=1,
                        status="needs_review",
                        rule_id="rename-import",
                        reason="file_not_fully_migrated",
                        caused_by=("generation_config_not_static",),
                    ),
                ),
            ),
        ),
        manifests=(),
        plans=(ImpactPlan(path="a.py"),),
        manifest_plan=ManifestPlan(),
    )


def test_the_answered_row_becomes_model_proposed_and_keeps_its_bail() -> None:
    """ADR-014 D6: the one written edit that names a bail."""
    folded = proposals.folded(driver(), session(decided()))
    rows = {(one.line, one.status): one for one in outcome_of(folded, "a.py").edits}
    assert (3, "model_proposed") in rows
    assert rows[(3, "model_proposed")].reason == "generation_config_not_static"
    assert rows[(3, "model_proposed")].rule_id is None
    # Untouched: nobody was asked about it.
    assert (1, "needs_review") in rows
    assert outcome_of(folded, "a.py").after == AFTER


def test_a_row_the_model_was_not_asked_about_is_not_re_graded() -> None:
    """Two findings share line 3, and an `unsupported` one is never the question (ADR-036 D1)."""
    run = driver()
    outcome = outcome_of(run, "a.py")
    with_surface = codemod.Outcome(
        path="a.py",
        before=outcome.before,
        after=outcome.after,
        edits=(
            *outcome.edits,
            Edit(path="a.py", line=3, status="unsupported", reason="attribute_removed"),
        ),
    )
    folded = proposals.folded(replace(run, files=(with_surface,)), session(decided()))
    statuses = sorted(one.status for one in outcome_of(folded, "a.py").edits if one.line == 3)
    assert statuses == ["model_proposed", "unsupported"]


def test_a_run_with_no_placement_is_handed_back_unchanged() -> None:
    run = driver()
    assert proposals.folded(run, proposals.Session(SETTINGS)) is run


def test_a_file_two_writers_rewrote_is_refused_rather_than_resolved() -> None:
    """ADR-039 D4: impossible, as a withheld row leaves its file unwritten, but asserted."""
    with pytest.raises(codemod.CodemodError, match="two answers for one path"):
        proposals.folded(driver(after=AFTER), session(decided()))


def test_a_placement_for_a_file_the_run_never_read_is_refused() -> None:
    with pytest.raises(codemod.CodemodError, match="did not read"):
        proposals.folded(driver(), session(decided(path="elsewhere.py")))


def test_the_heading_says_nothing_is_sent_when_nothing_is_configured() -> None:
    """The line printed before a run, and `--show-context`'s first line."""
    assert proposals.heading(SETTINGS) == "Model: qwen2.5-coder at localhost (openai_compat)."
    assert "none" in proposals.heading(ModelConfig())


def test_show_context_prints_every_string_the_payload_carries() -> None:
    """ADR-039 D2's claim, measured against the provider's own bytes."""
    one = consultation()
    made = adapter.build(SETTINGS, {})
    assert made is not None
    body = json.loads(made.request(one))
    printed = "\n".join(proposals.shown(SETTINGS, [one], []))
    for message in body["messages"]:
        assert message["content"] in printed
    assert body["model"] in printed
    assert "response_format=json_object" in printed
    assert "1 question(s); 0 finding(s) left for review are not asked about" in printed


def test_show_context_works_without_a_provider_and_names_no_endpoint() -> None:
    printed = "\n".join(proposals.shown(ModelConfig(), [consultation()], []))
    assert adapter.SYSTEM_PROMPT in printed
    assert adapter.question(consultation()) in printed
    assert "request fields" not in printed


def test_the_artefacts_are_named_the_way_adr_003_names_them() -> None:
    one = session(decided(), decided(2, path="b.py"))
    rows = proposals.records(one, apply=False, accept=False)
    summary = proposals.summary(one, rows)
    index = proposals.document(one, summary)
    names = [name for name, _ in proposals.artefacts(index, rows)]
    assert names == ["model/model.json", "model/proposals-1.json", "model/proposals-2.json"]
    assert summary.proposals == 2
    assert summary.accepted == 0
    assert (summary.tokens_in, summary.tokens_out) == (20, 4)
    assert index.consulted == 2


def test_the_prompt_is_recorded_only_when_the_configuration_asks_for_it() -> None:
    one = proposals.Session(SETTINGS, (decided(),), (), proposals.placement([decided()]))
    [row] = proposals.records(one, apply=False, accept=False)
    assert row.prompt is None
    assert row.prompt_sha256 == hashlib.sha256(b'{"messages": []}').hexdigest()

    loud = ModelConfig(**{**SETTINGS.model_dump(), "log_prompts": True})
    two = proposals.Session(loud, (decided(),), (), proposals.placement([decided()]))
    [kept] = proposals.records(two, apply=False, accept=False)
    assert kept.prompt == '{"messages": []}'


def test_a_consultation_that_was_never_answered_records_its_word() -> None:
    one = proposals.Session(
        SETTINGS,
        (
            proposals.Decided(
                asked=proposals.Asked(1, consultation(), b"{}"),
                failure="endpoint_unreachable",
                detail="http://localhost:11434/v1: connection refused",
            ),
        ),
    )
    [row] = proposals.records(one, apply=True, accept=True)
    assert (row.outcome, row.failure, row.proposal) == ("unanswered", "endpoint_unreachable", None)
    assert proposals.summary(one, [row]).proposals == 0


def test_a_consultation_answered_with_nothing_is_not_a_failure() -> None:
    one = proposals.Session(
        SETTINGS,
        (
            proposals.Decided(
                asked=proposals.Asked(1, consultation(), b"{}"), reply=base.Reply(None)
            ),
        ),
    )
    [row] = proposals.records(one, apply=True, accept=True)
    assert (row.outcome, row.failure, row.refusal) == ("nothing_proposed", None, None)


def test_the_consultation_reads_the_bytes_the_provider_says_it_sends() -> None:
    """One serialisation, so the hash is a hash of what went on the wire."""
    made = adapter.build(SETTINGS, {})
    assert made is not None
    one = consultation()
    assert made.request(one) == adapter.encode(adapter.payload(one, model=made.model))
