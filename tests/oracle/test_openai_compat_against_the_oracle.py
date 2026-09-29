"""The payload the adapter sends (`requests.yaml`) and the word for each reply (`replies.yaml`).

Real `urllib` calls to a local `http.server`, never a patched `urlopen`: that would stop measuring
ADR-038 D7's departures from the defaults (no proxy, redirect, cookies or compression).
"""

from __future__ import annotations

import http.server
import json
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import harness
import pytest
import yaml

from obelize.models import PROVIDER_FAILURES, ModelConfig
from obelize.providers import base
from obelize.providers import openai_compat as adapter

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "providers"
REQUESTS: dict[str, Any] = yaml.safe_load((FIXTURES / "requests.yaml").read_text(encoding="utf-8"))
REPLIES: dict[str, Any] = yaml.safe_load((FIXTURES / "replies.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["case"]: case for case in REPLIES["cases"]}
NAMES = [case["case"] for case in REPLIES["cases"]]

# The key lets the case whose endpoint quotes it back be graded on the echo.
ENVIRON = {"OBELIZE_MODEL_API_KEY": str(REPLIES["api_key"])}

# The slow endpoint: four times its case's deadline, short enough that the handler it strands
# ends before the module does.
SLOW_SECONDS = 1.0

# The request half's route, deliberately not a reply case.
REQUEST_ROUTE = "requests"


@dataclass(frozen=True, slots=True)
class Arrived:
    case: str
    path: str
    method: str
    headers: dict[str, str]
    body: bytes


# Every request, in order; module state is safe because tests run one at a time. The redirect
# case is graded on an entry that must not appear.
SEEN: list[Arrived] = []


def _sized(target: int) -> bytes:
    """Exactly `target` bytes, padded with `x` (never escaped), so one measurement is enough."""

    def built(pad: int) -> bytes:
        answer = {
            "proposal": {
                "path": "nested.py",
                "start_line": 31,
                "end_line": 34,
                "symbol": "google.generativeai.GenerativeModel",
                "replacement": "        model = new_genai.Client().models",
                "rationale": "x" * pad,
            }
        }
        message = {"role": "assistant", "content": json.dumps(answer)}
        return json.dumps({"choices": [{"index": 0, "message": message}]}).encode("utf-8")

    return built(1 + target - len(built(1)))


def _reply(case: dict[str, Any]) -> bytes:
    """The body a case answers with, in any of the key's four spellings."""
    if "generated" in case:
        if case["generated"]["kind"] == "completion_bytes":
            return _sized(int(case["generated"]["count"]))
        return b"x" * int(case["generated"]["count"])
    if "body" in case:
        return str(case["body"]).encode("utf-8")
    if "content" not in case:
        return b""
    envelope: dict[str, Any] = {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": case["content"]}}]
    }
    if "usage" in case:
        envelope["usage"] = case["usage"]
    return json.dumps(envelope).encode("utf-8")


class Endpoint(http.server.BaseHTTPRequestHandler):
    """Every case behind one port, chosen by the first segment of the path."""

    def do_POST(self) -> None:
        self._record("POST")
        case = CASES.get(self._case())
        if case is None:
            # The request half's route grades what arrived, so any reply `propose` accepts will do.
            self._answer(200, _reply(CASES["structured_output"]))
            return
        if case.get("transport") == "slow":
            time.sleep(SLOW_SECONDS)
            return
        self._answer(int(case.get("status", 200)), _reply(case), case.get("location"))

    def do_GET(self) -> None:
        # A followed 302 would arrive as GET.
        self._record("GET")
        self._answer(404, b"{}")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base signature
        """Silence the per-request log."""

    def _case(self) -> str:
        return self.path.strip("/").split("/")[0]

    def _record(self, method: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        SEEN.append(
            Arrived(
                case=self._case(),
                path=self.path,
                method=method,
                headers={key.lower(): value for key, value in self.headers.items()},
                body=self.rfile.read(length),
            )
        )

    def _answer(self, status: int, payload: bytes, location: str | None = None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            if location is not None:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            pass  # The client stopped reading, which is what the cap does.


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{int(httpd.server_address[1])}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _closed_port() -> int:
    """A port with nothing on it: the local runner that is not running."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _built(server: str, case: dict[str, Any], route: str | None = None) -> adapter.OpenAICompat:
    name = route or case["case"]
    host = server
    if case.get("transport") == "closed_port":
        host = f"http://127.0.0.1:{_closed_port()}"
    settings = ModelConfig(
        provider="openai_compat", base_url=f"{host}/{name}", model=str(REPLIES["model"])
    )
    made = adapter.build(settings, ENVIRON)
    assert made is not None
    if "deadline_s" in case:
        # Its own deadline, so grading the timeout does not cost the default two minutes.
        made.timeout_s = float(case["deadline_s"])
    return made


@dataclass(frozen=True, slots=True)
class Driven:
    root: Path
    consultation: base.Consultation
    asked: list[base.Consultation]


@pytest.fixture(scope="module")
def driven(tmp_path_factory: pytest.TempPathFactory) -> Driven:
    root, inputs = harness.driven(
        ROOT / REQUESTS["repository"], tmp_path_factory.mktemp("openai-compat"), REQUESTS["pack"]
    )
    asked, _ = base.questions(**inputs)
    wanted = [
        one
        for one in asked
        if one.context.path == REQUESTS["question"]["path"]
        and one.line == REQUESTS["question"]["line"]
    ]
    assert len(wanted) == 1, f"the key names a consultation the corpus does not make: {asked}"
    return Driven(root=root, consultation=wanted[0], asked=asked)


def test_the_message_is_the_one_the_key_writes_out(driven: Driven) -> None:
    """The whole payload, byte for byte: the test `docs/PRIVACY.md` is graded by."""
    assert adapter.question(driven.consultation) == REQUESTS["message"]


def test_the_message_states_the_labels_the_key_lists_and_no_others(driven: Driven) -> None:
    header = adapter.question(driven.consultation).split("\n\n")[0].splitlines()
    assert [line.split(": ")[0] + ": " for line in header] == list(REQUESTS["labels"])


def test_the_context_sits_once_between_the_two_markers(driven: Driven) -> None:
    message = adapter.question(driven.consultation)
    begin, end = REQUESTS["markers"]["begin"], REQUESTS["markers"]["end"]
    assert message.count(begin) == 1
    assert message.count(end) == 1
    assert message.endswith(end)
    assert message.split(begin)[1].split(end)[0] == "\n" + driven.consultation.context.text


def test_the_other_consultations_state_their_own_facts(driven: Driven) -> None:
    by_row = {(one.context.path, one.line): one for one in driven.asked}
    for row in REQUESTS["others"]:
        message = adapter.question(by_row[(row["path"], row["line"])])
        assert f"file: {row['path']}" in message
        assert f"lines sent: {row['lines_sent']}" in message
        assert f"line to change: {row['line']}" in message
        assert f"symbol at that line: {row['symbol']}" in message
        assert f"the rules refused with: {row['refused_with']}" in message


def test_the_request_on_the_wire_carries_the_payload_and_says_who_it_is(
    driven: Driven, server: str
) -> None:
    made = _built(server, CASES["structured_output"], route=f"{REQUEST_ROUTE}/v1")
    assert made.propose(driven.consultation).proposal is not None

    arrived = SEEN[-1]
    assert arrived.method == "POST"
    assert arrived.path == f"/{REQUEST_ROUTE}/v1{REQUESTS['endpoint']['appended']}"
    assert arrived.headers["content-type"] == REQUESTS["headers"]["content_type"]
    assert arrived.headers["accept"] == REQUESTS["headers"]["accept"]
    assert arrived.headers["user-agent"].startswith(REQUESTS["headers"]["user_agent"])
    assert arrived.headers["authorization"] == REQUESTS["headers"]["authorization"] + str(
        REPLIES["api_key"]
    )

    body = json.loads(arrived.body)
    assert sorted(body) == ["messages", "model", "response_format", "stream", "temperature"]
    # Sorted on the wire although the literal is not: the recorded request hash covers these bytes.
    assert arrived.body.startswith(b'{"messages"')
    assert [one["role"] for one in body["messages"]] == list(REQUESTS["body"]["roles"])
    assert body["model"] == REQUESTS["body"]["model"]
    assert body["temperature"] == REQUESTS["body"]["temperature"]
    assert body["stream"] == REQUESTS["body"]["stream"]
    assert body["response_format"] == {"type": REQUESTS["body"]["response_format"]}
    assert body["messages"][0]["content"] == adapter.SYSTEM_PROMPT
    assert body["messages"][1]["content"] == REQUESTS["message"]


def test_the_credential_in_the_file_reaches_no_part_of_the_request(
    driven: Driven, server: str
) -> None:
    """TM-3's own shape: a key in a comment, inside a context that is sent."""
    made = _built(server, CASES["structured_output"], route=f"{REQUEST_ROUTE}/secret")
    made.propose(driven.consultation)
    arrived = SEEN[-1]
    for secret in REQUESTS["must_not_appear"]:
        assert str(secret).encode("utf-8") not in arrived.body
        assert str(secret) not in json.dumps(dict(arrived.headers))


def test_a_proxy_in_the_environment_is_not_honoured(
    driven: Driven, server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`docs/PRIVACY.md`: `urllib`'s default opener would send payload and token via `http_proxy`.

    The proxy is this same server under its own route, so a request through it would be recorded.
    """
    monkeypatch.setenv("http_proxy", f"{server}/a_proxy")
    monkeypatch.setenv("https_proxy", f"{server}/a_proxy")
    made = _built(server, CASES["structured_output"], route=f"{REQUEST_ROUTE}/direct")
    assert made.propose(driven.consultation).proposal is not None
    assert SEEN[-1].path == f"/{REQUEST_ROUTE}/direct{REQUESTS['endpoint']['appended']}"
    assert [one.path for one in SEEN if one.case == "a_proxy"] == []


def test_the_url_is_appended_and_not_joined() -> None:
    """`urljoin` drops the base path: the trap ADR-038 D7 names."""
    base_url = "http://localhost:11434/v1"
    assert adapter.endpoint(base_url) == base_url + REQUESTS["endpoint"]["appended"]
    assert urljoin(base_url, "chat/completions") == "http://localhost:11434/chat/completions"


@pytest.mark.parametrize("name", NAMES)
def test_the_endpoint_behaviour_gets_the_word_the_key_names(
    name: str, driven: Driven, server: str
) -> None:
    case = CASES[name]
    made = _built(server, case)
    outcome = str(case["outcome"])
    if outcome in {"proposal", "no_proposal"}:
        reply = made.propose(driven.consultation)
        assert (reply.proposal is not None) is (outcome == "proposal")
        if "tokens_in" in case:
            assert (reply.tokens_in, reply.tokens_out) == (case["tokens_in"], case["tokens_out"])
        return
    with pytest.raises(base.ProviderError) as raised:
        made.propose(driven.consultation)
    assert raised.value.failure == outcome
    if "detail_holds" in case:
        assert str(case["detail_holds"]) in raised.value.detail


def test_every_word_in_the_vocabulary_is_reached(driven: Driven, server: str) -> None:
    """A word no case produces is measured by nothing."""
    reached = {str(case["outcome"]) for case in REPLIES["cases"]}
    assert reached >= PROVIDER_FAILURES
    assert reached - PROVIDER_FAILURES == {"proposal", "no_proposal"}


def test_the_rejected_key_is_not_in_what_is_recorded(driven: Driven, server: str) -> None:
    """The gateway echoes the key; redaction before the cut (ADR-038 D8) removes only the key."""
    case = CASES["unauthorised"]
    assert case["detail_redacts_the_key"] is True
    with pytest.raises(base.ProviderError) as raised:
        _built(server, case).propose(driven.consultation)
    assert str(REPLIES["api_key"]) not in raised.value.detail
    assert "[REDACTED:OBELIZE_MODEL_API_KEY]" in raised.value.detail
    assert "Incorrect API key provided" in raised.value.detail


def test_a_redirect_is_not_followed(driven: Driven, server: str) -> None:
    """The payload and the bearer token stay on the configured host."""
    case = CASES["moved_elsewhere"]
    with pytest.raises(base.ProviderError) as raised:
        _built(server, case).propose(driven.consultation)
    assert raised.value.failure == "endpoint_redirected"
    target = str(case["location"]).strip("/").split("/")[0]
    assert case["second_request"] is False
    assert [one.path for one in SEEN if one.case == target] == []


def test_a_whole_run_with_no_provider_opens_no_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gate 3 over a whole run: scan, rules and selection complete with sockets blocked."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a run with no provider opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    _, inputs = harness.driven(ROOT / REQUESTS["repository"], tmp_path, REQUESTS["pack"])
    asked, _ = base.questions(**inputs)
    assert asked
    assert adapter.build(ModelConfig(), {}) is None
