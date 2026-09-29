"""Adapter cases no fixture or local server reaches: message shapes, transport errors, constants.

The opener is stubbed, not the endpoint, where `urllib` raises before any HTTP status exists.
"""

from __future__ import annotations

import email.message
import http.client
import io
import json
import socket
import urllib.error
import urllib.request
from typing import Any

import pytest

from obelize.models import PROVIDER_FAILURES, ModelConfig
from obelize.providers import base, guard
from obelize.providers import openai_compat as adapter

GOOD = json.dumps(
    {
        "proposal": {
            "path": "app.py",
            "start_line": 1,
            "end_line": 2,
            "symbol": "legacy.Thing",
            "replacement": "x = 1",
            "rationale": "because",
        }
    }
)


def _completion(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def _consultation(**changes: Any) -> base.Consultation:
    fields: dict[str, Any] = {
        "context": base.Context(path="app.py", start_line=1, end_line=2, text="x = 1\ny = 2\n"),
        "line": 1,
        "column": 0,
        "symbol": "legacy.Thing",
        "bail": "client_source_unresolved",
        "pack_id": "demo/pack",
        "to_package": "new-package",
        "to_modules": ("new.package",),
        "limitations": ("One thing it will not do.",),
    }
    fields.update(changes)
    return base.Consultation(**fields)


class _Answer:
    """A response body for a caller that reads it once, with a size cap."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, amount: int) -> bytes:
        return self.body[:amount]

    def __enter__(self) -> _Answer:
        return self

    def __exit__(self, *unused: object) -> None:
        return None


class _Stub:
    def __init__(self, outcome: bytes | Exception) -> None:
        self.outcome = outcome
        self.seen: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout: float | None = None) -> _Answer:
        self.seen.append(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return _Answer(self.outcome)


def _adapter(
    monkeypatch: pytest.MonkeyPatch,
    outcome: bytes | Exception,
    environ: dict[str, str] | None = None,
) -> tuple[adapter.OpenAICompat, _Stub]:
    made = adapter.OpenAICompat(
        url="https://example.invalid/v1/chat/completions",
        model="a-model",
        environ={} if environ is None else environ,
        api_key_env="OBELIZE_MODEL_API_KEY",
    )
    stub = _Stub(outcome)
    monkeypatch.setattr(made, "opener", stub)
    return made, stub


def _refusal(monkeypatch: pytest.MonkeyPatch, outcome: bytes | Exception) -> base.ProviderError:
    made, _ = _adapter(monkeypatch, outcome)
    with pytest.raises(base.ProviderError) as raised:
        made.propose(_consultation())
    return raised.value


def _http_error(code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.invalid/v1/chat/completions",
        code,
        "Something",
        email.message.Message(),
        io.BytesIO(body),
    )


def test_the_vocabulary_is_the_nine_words_the_adr_names() -> None:
    """A word added without a corpus case would be graded by nothing."""
    assert sorted(PROVIDER_FAILURES) == [
        "answer_not_a_proposal",
        "answer_not_json",
        "endpoint_redirected",
        "endpoint_refused",
        "endpoint_unreachable",
        "proposal_does_not_hold",
        "response_not_a_completion",
        "response_not_json",
        "response_too_large",
    ]


def test_the_response_cap_is_far_above_the_largest_answer_that_could_be_accepted() -> None:
    """ADR-038 D7: a guard-limit replacement, doubled for JSON escaping, fits with room to spare."""
    assert adapter.RESPONSE_BYTE_LIMIT > guard.REPLACEMENT_BYTE_LIMIT * 4


def test_the_deadline_is_shorter_than_a_verification_run() -> None:
    """One completion is not somebody's whole test suite (ADR-038 D5)."""
    assert 0 < adapter.REQUEST_TIMEOUT_S < 600


def test_the_system_prompt_asks_for_what_the_guard_enforces() -> None:
    """The guard refuses these imports (ADR-037 D7); an untold model is refused for obeying."""
    for named in ("__import__", "importlib.import_module", '{"proposal": null}'):
        assert named in adapter.SYSTEM_PROMPT
    assert adapter.CONTEXT_BEGIN in adapter.SYSTEM_PROMPT
    assert adapter.CONTEXT_END in adapter.SYSTEM_PROMPT


def test_the_system_prompt_names_no_pack_and_no_migration() -> None:
    """Fixed means the same bytes in every request, whatever is migrated."""
    assert "google" not in adapter.SYSTEM_PROMPT
    assert "gemini" not in adapter.SYSTEM_PROMPT.lower()


def test_a_pack_with_no_limitations_sends_no_pack_note() -> None:
    message = adapter.question(_consultation(limitations=()))
    assert adapter.PACK_NOTE not in message
    assert message.splitlines()[8] == ""
    assert message.splitlines()[9] == adapter.CONTEXT_BEGIN


def test_a_pack_that_renames_no_import_licenses_nothing() -> None:
    assert "modules a proposal may import: (none)" in adapter.question(_consultation(to_modules=()))


def test_a_finding_with_no_symbol_says_so() -> None:
    assert "symbol at that line: (not recorded)" in adapter.question(_consultation(symbol=None))


def test_a_context_that_does_not_end_in_a_newline_still_ends_its_line() -> None:
    """Without it the end marker glues to the code and the payload depends on how the file ends."""
    context = base.Context(path="app.py", start_line=1, end_line=1, text="x = 1")
    message = adapter.question(_consultation(context=context))
    assert message.endswith(f"x = 1\n{adapter.CONTEXT_END}")


def test_the_body_is_the_same_bytes_twice() -> None:
    one = adapter.encode(adapter.payload(_consultation(), model="a-model"))
    two = adapter.encode(adapter.payload(_consultation(), model="a-model"))
    assert one == two


def test_a_context_that_is_not_ascii_travels_as_itself() -> None:
    dash = chr(0x2014)
    context = base.Context(path="app.py", start_line=1, end_line=1, text=f"x = 1  # {dash}\n")
    body = adapter.encode(adapter.payload(_consultation(context=context), model="a-model"))
    assert dash.encode("utf-8") in body
    assert rb"\u2014" not in body


def test_a_trailing_slash_does_not_double_the_separator() -> None:
    assert adapter.endpoint("http://host/v1/") == "http://host/v1/chat/completions"
    assert adapter.endpoint("http://host/v1") == "http://host/v1/chat/completions"


def test_no_provider_is_no_adapter() -> None:
    """Gate 3: the rules work with no model at all."""
    assert adapter.build(ModelConfig(), {}) is None


def test_a_configured_provider_is_an_adapter_pointed_at_it() -> None:
    settings = ModelConfig(
        provider="openai_compat",
        base_url="http://localhost:11434/v1",
        model="qwen",
        api_key_env="SOME_OTHER_KEY",
    )
    made = adapter.build(settings, {"SOME_OTHER_KEY": "x"})
    assert made is not None
    assert made.url == "http://localhost:11434/v1/chat/completions"
    assert made.model == "qwen"
    assert made.api_key_env == "SOME_OTHER_KEY"
    assert made.timeout_s == adapter.REQUEST_TIMEOUT_S


def test_deciding_there_is_no_provider_opens_no_socket() -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a run with no provider opened a socket")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket, "socket", refuse)
        patch.setattr(socket, "create_connection", refuse)
        assert adapter.build(ModelConfig(), {}) is None


def test_a_key_in_the_environment_is_a_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    made, stub = _adapter(monkeypatch, _completion(GOOD), {"OBELIZE_MODEL_API_KEY": "sk-abc"})
    made.propose(_consultation())
    assert _headers(stub)["authorization"] == "Bearer sk-abc"


def test_no_key_in_the_environment_is_no_header_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """A local Ollama wants no credential (ADR-038 D9)."""
    made, stub = _adapter(monkeypatch, _completion(GOOD), {"OBELIZE_MODEL_API_KEY": ""})
    made.propose(_consultation())
    assert "authorization" not in _headers(stub)


def _headers(stub: _Stub) -> dict[str, str]:
    return {key.lower(): value for key, value in stub.seen[-1].header_items()}


@pytest.mark.parametrize(
    "raised",
    [
        urllib.error.URLError("no route to host"),
        http.client.BadStatusLine("nonsense"),
        OSError("the connection was reset"),
    ],
    ids=["url_error", "bad_status_line", "os_error"],
)
def test_nothing_answered_is_one_word(monkeypatch: pytest.MonkeyPatch, raised: Exception) -> None:
    assert _refusal(monkeypatch, raised).failure == "endpoint_unreachable"


def test_a_long_refusal_is_cut_and_says_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoint's words are bounded; redaction runs before the cut (ADR-038 D8)."""
    error = _refusal(monkeypatch, _http_error(500, b"x" * 3000))
    assert error.failure == "endpoint_refused"
    assert "characters)" in error.detail
    assert len(error.detail) < 600


def test_a_refusal_at_exactly_the_limit_is_not_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = len("HTTP 500 Something: ")
    error = _refusal(monkeypatch, _http_error(500, b"x" * (adapter.DETAIL_LIMIT - prefix)))
    assert len(error.detail) == adapter.DETAIL_LIMIT
    assert "characters)" not in error.detail


def test_the_cut_happens_after_the_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key straddling the cut: cutting first would leave its first twenty characters behind.

    `redact.py` accepts a secret cut by its own elision; that is no licence to cut one here.
    """
    key = "sk-fixture-secret-value"
    prefix = len("HTTP 500 Something: ")
    body = ("y" * (adapter.DETAIL_LIMIT - 20 - prefix) + key + "z" * 200).encode("utf-8")
    made, _ = _adapter(monkeypatch, _http_error(500, body), {"OBELIZE_MODEL_API_KEY": key})
    with pytest.raises(base.ProviderError) as raised:
        made.propose(_consultation())
    assert key[:12] not in raised.value.detail
    assert "[REDACTED" in raised.value.detail


def test_a_body_that_is_json_and_not_an_object_is_not_a_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _refusal(monkeypatch, b"[]").failure == "response_not_a_completion"


def test_a_choice_that_is_not_an_object_is_not_a_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps({"choices": ["a sentence"]}).encode("utf-8")
    assert _refusal(monkeypatch, body).failure == "response_not_a_completion"


def test_content_that_is_not_a_string_is_not_a_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps({"choices": [{"message": {"content": 5}}]}).encode("utf-8")
    assert _refusal(monkeypatch, body).failure == "response_not_a_completion"


def test_a_usage_that_is_not_an_object_is_no_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero counts, not an exception: the answer itself is still good."""
    body = json.dumps({"choices": [{"message": {"content": GOOD}}], "usage": "lots"}).encode()
    made, _ = _adapter(monkeypatch, body)
    reply = made.propose(_consultation())
    assert (reply.tokens_in, reply.tokens_out) == (0, 0)


def test_an_answer_that_is_json_and_not_an_object_is_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not the envelope, and it has no braces for the object search to find."""
    assert _refusal(monkeypatch, _completion("[1, 2]")).failure == "answer_not_json"
