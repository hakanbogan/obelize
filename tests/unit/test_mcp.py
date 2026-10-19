"""`obelize mcp`: the protocol, what a tool may be given, and the commands behind each tool."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from obelize.cli import app
from obelize.mcp import residue, server, tools
from obelize.providers import base
from platforms import PYTHON
from support import commit_all, committed

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

PACK = "gemini/google-generativeai-to-google-genai"
RUN = "20261018T143956Z-22ec1be2"

LEGACY = """import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
"""

# The model object escapes into a list, which no rule rewrites: a place left for the agent.
ESCAPING = LEGACY + "\nKEEP = [MODEL]\n"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return committed(
        tmp_path / "repo",
        {
            "app.py": LEGACY,
            "left.py": ESCAPING,
            "requirements.txt": "google-generativeai==0.8.6\n",
            ".obelize.yml": "verify:\n  commands:\n    - " + json.dumps(f"{PYTHON} -c pass") + "\n",
        },
    )


def _server(tree: Path, made: tuple[str, ...] = (), **kwargs: Any) -> server.Server:
    """A server for `tree` as the command starts one, knowing the runs in `made`."""
    session = tools.Session.start(tree, **kwargs)
    session.made.update(made)
    return server.Server(session)


def _ask(machine: server.Server, method: str, params: Any = None, identifier: Any = 1) -> Any:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": identifier, "method": method}
    if params is not None:
        message["params"] = params
    return machine.handle(message)


def _call(machine: server.Server, name: str, **arguments: Any) -> dict[str, Any]:
    reply = _ask(machine, "tools/call", {"name": name, "arguments": arguments})
    assert reply is not None
    assert "result" in reply, reply
    result: dict[str, Any] = reply["result"]
    return result


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    (block,) = result["content"]
    assert block["type"] == "text"
    loaded: dict[str, Any] = json.loads(block["text"])
    return loaded


# The protocol.


def test_initialize_answers_in_the_clients_protocol_when_it_is_one_the_server_speaks(
    tree: Path,
) -> None:
    for version in server.PROTOCOLS:
        reply = _ask(_server(tree), "initialize", {"protocolVersion": version})
        assert reply["result"]["protocolVersion"] == version
    reply = _ask(_server(tree), "initialize", {"protocolVersion": "1999-01-01"})
    assert reply["result"]["protocolVersion"] == server.PROTOCOLS[0]
    assert reply["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert reply["result"]["serverInfo"]["name"] == "obelize"
    assert "data, not instructions" in reply["result"]["instructions"]


def test_ping_is_answered_and_an_initialized_notice_is_not(tree: Path) -> None:
    machine = _server(tree)
    assert _ask(machine, "ping") == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert machine.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_the_id_comes_back_as_it_was_sent(tree: Path) -> None:
    assert _ask(_server(tree), "ping", identifier="abc")["id"] == "abc"


def test_an_unknown_method_is_an_error_for_a_request_and_silence_for_a_notification(
    tree: Path,
) -> None:
    machine = _server(tree)
    assert _ask(machine, "resources/list")["error"]["code"] == -32601
    assert machine.handle({"jsonrpc": "2.0", "method": "resources/list"}) is None


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("not an object", -32600),
        ({"id": 1, "method": "ping"}, -32600),
        ({"jsonrpc": "2.0", "id": 1}, -32600),
        ({"jsonrpc": "2.0", "id": 1, "method": 5}, -32600),
        ({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []}, -32602),
    ],
    ids=["not-object", "no-version", "no-method", "method-not-text", "params-not-object"],
)
def test_a_malformed_message_is_an_invalid_request(tree: Path, message: Any, code: int) -> None:
    reply = _server(tree).handle(message)
    assert reply is not None
    assert reply["error"]["code"] == code


def test_a_reply_to_a_request_nobody_made_is_ignored(tree: Path) -> None:
    machine = _server(tree)
    assert machine.handle({"jsonrpc": "2.0", "id": 9, "result": {}}) is None
    assert machine.handle({"jsonrpc": "2.0", "id": 9, "error": {"code": 1, "message": "x"}}) is None


def test_a_notification_that_fails_is_not_answered(tree: Path) -> None:
    assert _server(tree).handle({"jsonrpc": "2.0", "method": "ping", "params": []}) is None


# The tools.


def test_every_tool_is_listed_with_a_closed_schema_and_the_hints_a_client_asks_on(
    tree: Path,
) -> None:
    listed = _ask(_server(tree), "tools/list")["result"]["tools"]
    assert [tool["name"] for tool in listed] == [
        "obelize_scan",
        "obelize_plan",
        "obelize_apply",
        "obelize_residue",
        "obelize_verify",
        "obelize_report",
        "obelize_undo",
    ]
    for tool in listed:
        assert tool["inputSchema"]["additionalProperties"] is False
        assert tool["description"]
    writes = {tool["name"] for tool in listed if tool["annotations"]["destructiveHint"]}
    assert writes == {"obelize_apply", "obelize_undo"}
    assert {tool["name"] for tool in listed if tool["annotations"]["readOnlyHint"]} == {
        tool["name"] for tool in listed
    } - writes


def test_no_tool_takes_a_command_a_path_or_a_consent(tree: Path) -> None:
    """What the person who started the server decided stays theirs: nothing an agent can pass
    names a command to run, a place on disk, a model or a trust."""
    listed = _ask(_server(tree), "tools/list")["result"]["tools"]
    names = {name for tool in listed for name in tool["inputSchema"]["properties"]}
    assert names == {"packs", "library", "modules", "limit", "run", "current"}


def test_a_server_started_read_only_offers_no_tool_that_writes_source_files(tree: Path) -> None:
    machine = _server(tree, read_only=True)
    listed = {tool["name"] for tool in _ask(machine, "tools/list")["result"]["tools"]}
    assert not listed & {"obelize_apply", "obelize_undo"}
    reply = _ask(machine, "tools/call", {"name": "obelize_apply", "arguments": {}})
    assert reply["error"]["code"] == -32602


def test_an_unknown_tool_and_arguments_that_are_no_object_are_protocol_errors(tree: Path) -> None:
    machine = _server(tree)
    assert _ask(machine, "tools/call", {"name": "obelize_rm"})["error"]["code"] == -32602
    assert _ask(machine, "tools/call", {})["error"]["code"] == -32602
    bad = _ask(machine, "tools/call", {"name": "obelize_scan", "arguments": []})
    assert bad["error"]["code"] == -32602


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("obelize_scan", {"verify": "rm -rf /"}, "unknown argument(s) verify"),
        ("obelize_scan", {"repo": "/etc"}, "unknown argument(s) repo"),
        ("obelize_scan", {"packs": ["--model"]}, "packs takes a list of at most 32 names"),
        (
            "obelize_scan",
            {"packs": "py-pdf/pypdf2-to-pypdf"},
            "packs takes a list of at most 32 names",
        ),
        ("obelize_scan", {"packs": ["../../etc/passwd"]}, "packs takes a list of at most 32 names"),
        ("obelize_scan", {"modules": ["yaml"]}, "pass library too"),
        ("obelize_scan", {"library": "-x"}, "library takes a distribution name"),
        ("obelize_scan", {"library": 3}, "library takes a distribution name"),
        (
            "obelize_scan",
            {"library": "requests", "modules": ["a b"]},
            "modules takes a list of at most 32 names",
        ),
        ("obelize_scan", {"library": "requests", "packs": [PACK]}, "has no pack"),
        ("obelize_plan", {"accept_model": True}, "unknown argument(s) accept_model"),
        ("obelize_apply", {"allow_dirty": True}, "unknown argument(s) allow_dirty"),
        ("obelize_verify", {}, "run takes a run id"),
        ("obelize_verify", {"run": "../../x"}, "run takes a run id"),
        ("obelize_verify", {"run": RUN, "current": "yes"}, "current takes true or false"),
        ("obelize_verify", {"run": RUN}, "is not a run this session made"),
        ("obelize_undo", {"run": RUN}, "is not a run this session made"),
        ("obelize_scan", {"packs": ["x/y"]}, "which obelize does not know"),
        ("obelize_plan", {"packs": [f"{PACK}x"]}, "which obelize does not know"),
        ("obelize_scan", {"packs": [PACK] * 33}, "at most 32 names"),
        ("obelize_scan", {"library": "requests", "modules": ["m"] * 33}, "at most 32 names"),
        ("obelize_undo", {"run": 7}, "run takes a run id"),
        ("obelize_residue", {"limit": 0}, "limit takes a whole number"),
        ("obelize_residue", {"limit": 201}, "limit takes a whole number"),
        ("obelize_residue", {"limit": True}, "limit takes a whole number"),
        ("obelize_residue", {"limit": "5"}, "limit takes a whole number"),
        ("obelize_report", {"run": "latest; rm"}, "run takes a run id"),
    ],
)
def test_an_argument_that_could_name_a_flag_a_path_or_a_command_is_refused(
    tree: Path, name: str, arguments: dict[str, Any], message: str
) -> None:
    result = _call(_server(tree), name, **arguments)
    assert result["isError"] is True
    assert message in _payload(result)["error"]
    assert not (tree / ".obelize" / "runs").exists()


# What a tool does.


def test_scan_returns_the_findings_document_and_where_the_evidence_is(tree: Path) -> None:
    result = _call(_server(tree), "obelize_scan")
    payload = _payload(result)
    assert result["isError"] is False
    assert payload["exit_code"] == 0
    assert payload["meaning"] == tools.MEANING[0]
    assert payload["evidence"] == f".obelize/runs/{payload['run']}"
    assert payload["result"]["packs"][0]["id"] == PACK
    assert payload["result"]["counts"]["findings"] > 0


def test_scan_lists_a_library_with_no_pack(tree: Path) -> None:
    payload = _payload(
        _call(
            _server(tree),
            "obelize_scan",
            library="google-generativeai",
            modules=["google.generativeai"],
        )
    )
    assert payload["result"]["packs"][0]["id"] == "inventory/google-generativeai"
    rows = [row for row in payload["result"]["findings"] if row["kind"] != "manifest"]
    assert rows
    assert {row["bail"] for row in rows} == {"no_pack_for_usage"}


def test_plan_returns_the_diff_and_writes_nothing(tree: Path) -> None:
    before = (tree / "app.py").read_bytes()
    payload = _payload(_call(_server(tree), "obelize_plan"))
    assert payload["exit_code"] == 0
    assert payload["result"]["files"]
    assert (tree / "app.py").read_bytes() == before


def test_apply_writes_the_provable_part_and_runs_the_trusted_verification(tree: Path) -> None:
    result = _call(_server(tree, trust=True), "obelize_apply")
    payload = _payload(result)
    assert payload["exit_code"] == 4, payload
    assert result["isError"] is False
    assert "genai.Client" in (tree / "app.py").read_text(encoding="utf-8")
    assert payload["verify"]["status"] == "pass"
    assert payload["verify"]["baseline"]["status"] == "pass"
    assert payload["verify"]["commands"][0]["source"] == "repo_config"


def test_a_repositorys_own_verification_command_is_not_run_for_an_agent_unless_the_person_trusts_it(
    tree: Path,
) -> None:
    """The change is written, as `fix --apply --non-interactive` writes it, and the record says no
    verdict was reached, so the agent can see that the tests have not judged it."""
    payload = _payload(_call(_server(tree), "obelize_apply"))
    assert payload["exit_code"] == 5, payload
    assert payload["verify"]["status"] == "not_run"
    assert payload["verify"]["reason"] == "policy_refused"
    assert payload["verify"]["commands"] == []


def test_a_repository_that_is_not_committed_is_refused_not_written(tree: Path) -> None:
    (tree / "app.py").write_text(LEGACY + "\n# edited\n", encoding="utf-8")
    result = _call(_server(tree, trust=True), "obelize_apply")
    payload = _payload(result)
    assert payload["exit_code"] == 5
    assert payload["meaning"] == tools.MEANING[5]
    assert result["isError"] is False
    assert "genai.Client" not in (tree / "app.py").read_text(encoding="utf-8")


def test_the_loop_an_agent_runs_apply_residue_edit_verify_current_undo(tree: Path) -> None:
    machine = _server(tree, trust=True)
    applied = _payload(_call(machine, "obelize_apply"))
    run_id = applied["run"]
    places = _payload(_call(machine, "obelize_residue"))
    assert places["total"] > 0
    assert any(place["context"] for place in places["places"])
    (tree / "app.py").write_text("migrated = True\n", encoding="utf-8")
    refused = _payload(_call(machine, "obelize_verify", run=run_id))
    assert refused["exit_code"] == 6
    checked = _payload(_call(machine, "obelize_verify", run=run_id, current=True))
    assert checked["exit_code"] == 0
    assert checked["result"]["verify"]["edited"] == ["app.py"]
    report = _payload(_call(machine, "obelize_report", run=run_id))
    assert report["run"] == run_id
    assert "Verified again" in report["report"]
    undone = _payload(_call(machine, "obelize_undo", run=run_id))
    assert undone["exit_code"] == 4
    assert {row["outcome"] for row in undone["result"]["files"]} == {"reverted", "skipped"}


def test_report_defaults_to_the_latest_run(tree: Path) -> None:
    machine = _server(tree)
    _call(machine, "obelize_scan")
    latest = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    assert _payload(_call(machine, "obelize_report"))["run"] == latest


def test_report_for_a_run_that_does_not_exist_is_an_error_result(tree: Path) -> None:
    result = _call(_server(tree), "obelize_report", run=RUN)
    assert result["isError"] is True
    assert f"there is no run {RUN}" in _payload(result)["error"]


def test_report_with_no_run_yet_is_an_error_result(tree: Path) -> None:
    result = _call(_server(tree), "obelize_report")
    assert result["isError"] is True


def test_a_usage_error_of_a_command_is_an_error_result_and_an_outcome_is_not(tree: Path) -> None:
    result = _call(_server(tree, made=(RUN,)), "obelize_verify", run=RUN)
    assert result["isError"] is True
    assert _payload(result)["exit_code"] == 2


def test_residue_gives_the_code_around_each_place_and_what_to_do(tree: Path) -> None:
    payload = _payload(_call(_server(tree), "obelize_residue", limit=2))
    assert payload["shown"] == 2
    assert payload["total"] >= 2
    first = payload["places"][0]
    assert first["context"]["text"]
    assert first["context"]["start_line"] <= first["line"] <= first["context"]["end_line"]
    assert first["action"]
    assert payload["packs"][0]["id"] == PACK


def test_residue_redacts_what_the_model_adapter_would_redact(tree: Path) -> None:
    payload = _payload(_call(_server(tree), "obelize_residue", limit=200))
    text = "".join(place["context"]["text"] for place in payload["places"] if place["context"])
    assert "AIzaNotARealKey" not in text


def test_residue_of_a_scan_that_failed_is_the_commands_own_answer(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        tools.Session, "run", lambda *_args: tools.Completed(2, "", "a usage error\n")
    )
    result = _call(_server(tree), "obelize_residue")
    assert result["isError"] is True
    assert _payload(result)["exit_code"] == 2


# The commands behind the tools.


def test_a_command_stopped_at_its_deadline_is_an_error_result(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def hang(*_args: Any, **_kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("obelize", 1)

    monkeypatch.setattr(subprocess, "run", hang)
    result = _call(_server(tree), "obelize_scan")
    assert result["isError"] is True
    assert "stopped after 900 s" in _payload(result)["error"]


def test_a_command_gets_no_input_and_its_output_is_captured(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen.update(argv=argv, **kwargs)
        return subprocess.CompletedProcess(argv, 0, b"plain text\n", b"warning\nEvidence: x\n")

    monkeypatch.setattr(subprocess, "run", fake)
    payload = _payload(_call(_server(tree), "obelize_scan"))
    assert seen["stdin"] == subprocess.DEVNULL
    assert seen["capture_output"] is True
    assert seen["cwd"] == tree
    assert seen["argv"][:4] == [sys.executable, "-P", "-m", "obelize"]
    assert seen["env"]["NO_COLOR"] == "1"
    assert payload["output"] == "plain text\n"
    assert payload["notes"] == "warning"
    assert payload["evidence"] == "x"
    assert "result" not in payload


def test_trust_is_passed_on_only_when_the_person_gave_it(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def fake(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"{}", b"")

    monkeypatch.setattr(subprocess, "run", fake)
    for trust in (False, True):
        _call(_server(tree, made=(RUN,), trust=trust), "obelize_verify", run=RUN)
        _call(_server(tree, trust=trust), "obelize_apply")
    flags = ["--trust-repo-config" in argv for argv in seen]
    assert flags == [False, False, True, True]
    assert all("--non-interactive" in argv for argv in seen)
    assert all("--allow-dirty" not in argv and "--accept-model" not in argv for argv in seen)
    assert all(argv[argv.index("--model") + 1] == "none" for argv in seen if "--model" in argv)


def test_a_result_longer_than_the_limit_is_cut_and_says_so() -> None:
    rows = [{"path": f"file{n}.py", "note": "x" * 100} for n in range(5000)]
    payload = tools._fit({"result": {"findings": rows}})
    assert len(json.dumps(payload, indent=2)) <= tools.LIMIT
    assert payload["truncated"].startswith("findings cut to ")
    assert payload["result"]["findings"]


def test_a_result_no_list_can_shrink_enough_is_left_out_and_says_so() -> None:
    payload = tools._fit({"exit_code": 0, "result": {"files": [], "blob": "x" * (tools.LIMIT * 2)}})
    assert "result" not in payload
    assert payload["truncated"] == "the result is over the limit; read the run folder instead"


def test_the_longest_list_is_the_one_cut() -> None:
    payload = tools._fit(
        {"result": {"short": ["a", "b"], "long": [{"n": "x" * 1000}] * 400, "count": 1}}
    )
    assert payload["truncated"].startswith("long cut to ")
    assert payload["result"]["short"] == ["a", "b"]


def test_a_result_within_the_limit_is_left_alone() -> None:
    payload = {"result": {"findings": [{"a": 1}]}}
    assert tools._fit(payload) == {"result": {"findings": [{"a": 1}]}}
    assert tools._fit({"result": {"counts": 1}}) == {"result": {"counts": 1}}


# The stream.


def _lines(machine: server.Server, text: bytes) -> list[dict[str, Any]]:
    sink = io.BytesIO()
    machine.serve(io.BytesIO(text), sink)
    return [json.loads(line) for line in sink.getvalue().splitlines()]


def test_the_stream_answers_each_line_with_one_line(tree: Path) -> None:
    ask = b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
    replies = _lines(_server(tree), ask)
    assert [reply["id"] for reply in replies] == [1, 2]


def test_a_line_that_is_not_json_is_a_parse_error_and_the_stream_goes_on(tree: Path) -> None:
    replies = _lines(_server(tree), b'{oops\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n')
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["id"] == 2


def test_a_line_that_is_not_utf8_is_a_parse_error(tree: Path) -> None:
    assert _lines(_server(tree), b"\xff\xfe\n")[0]["error"]["code"] == -32700


def test_a_message_over_the_limit_is_refused_and_ends_the_stream(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "MAX_MESSAGE", 10)
    ask = b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
    replies = _lines(_server(tree), ask)
    assert [reply["error"]["message"] for reply in replies] == ["message too large"]


def test_a_message_nested_past_what_python_reads_is_a_parse_error(tree: Path) -> None:
    replies = _lines(
        _server(tree), b"[" * 200_000 + b"\n" + b'{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
    )
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["id"] == 2


def test_a_fault_of_the_servers_own_is_an_internal_error_and_not_the_end_of_the_session(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = _server(tree)

    def broken(_params: Any) -> None:
        raise OSError("argument list too long")

    monkeypatch.setitem(machine._methods, "ping", broken)
    replies = _lines(
        machine,
        b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n{"jsonrpc":"2.0","method":"ping"}\n'
        b'{"jsonrpc":"2.0","id":3,"method":"tools/list"}\n',
    )
    assert [reply["id"] for reply in replies] == [1, 3]
    assert replies[0]["error"] == {"code": -32603, "message": "Internal error"}
    assert "OSError in ping" in capsys.readouterr().err


def test_a_tool_that_fails_in_a_way_nobody_foresaw_is_an_error_result(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def hang(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("argument list too long")

    monkeypatch.setattr(subprocess, "run", hang)
    result = _call(_server(tree), "obelize_scan")
    assert result["isError"] is True
    assert _payload(result) == {"error": "OSError"}


def test_the_command_serves_standard_input_and_output(tree: Path) -> None:
    ask = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
    result = runner.invoke(app, ["mcp", "--repo", str(tree), "--read-only"], input=ask)
    assert result.exit_code == 0
    (reply,) = [json.loads(line) for line in result.stdout_bytes.splitlines()]
    assert "obelize_apply" not in {tool["name"] for tool in reply["result"]["tools"]}


def test_the_command_refuses_a_repository_that_is_not_a_directory(tmp_path: Path) -> None:
    result = runner.invoke(app, ["mcp", "--repo", str(tmp_path / "nothing")])
    assert result.exit_code == 2
    assert "is not a directory" in result.output


def test_the_command_pins_the_configuration_that_the_trust_it_is_given_covers(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions: list[tools.Session] = []
    monkeypatch.setattr(server, "serve", sessions.append)
    result = runner.invoke(app, ["mcp", "--repo", str(tree), "--trust-repo-config"])
    assert result.exit_code == 0
    assert sessions[0].flags == ["--trust-repo-config"]
    (tree / ".obelize.yml").write_text("verify:\n  commands: []\n", encoding="utf-8")
    with pytest.raises(tools.ToolError, match="not the file the server was started with"):
        _ = sessions[0].flags


def test_a_client_that_goes_away_mid_reply_ends_the_server_quietly(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def gone(_session: tools.Session) -> None:
        raise BrokenPipeError

    monkeypatch.setattr(server, "serve", gone)
    assert runner.invoke(app, ["mcp", "--repo", str(tree)]).exit_code == 0


def test_a_real_server_process_writes_only_protocol_to_standard_output(tree: Path) -> None:
    asks = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "obelize_scan", "arguments": {}},
        },
    ]
    done = subprocess.run(
        [sys.executable, "-m", "obelize", "mcp", "--repo", str(tree)],
        input=b"".join(json.dumps(ask).encode() + b"\n" for ask in asks),
        capture_output=True,
        timeout=300,
        check=False,
    )
    assert done.returncode == 0
    assert done.stderr == b""
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2]
    assert all(reply["jsonrpc"] == "2.0" for reply in replies)
    assert json.loads(replies[1]["result"]["content"][0]["text"])["exit_code"] == 0


# The places left.


def test_a_window_is_the_smallest_scope_around_the_line_and_is_redacted() -> None:
    source = b'def a():\n    key = "AIzaSyD00000000000000000000000000000000"\n    return key\n'
    context = base.excerpt("m.py", source, 2, {})
    assert context is not None
    assert (context.start_line, context.end_line) == (1, 3)
    assert "AIzaSyD" not in context.text


def test_no_window_exists_for_a_file_that_does_not_parse() -> None:
    assert base.excerpt("m.py", b"def (:\n", 1, {}) is None


def test_the_places_of_a_library_with_no_pack_have_no_guide(tmp_path: Path) -> None:
    root = committed(tmp_path / "repo", {"app.py": "import requests\nrequests.get('x')\n"})
    done = subprocess.run(
        [sys.executable, "-m", "obelize", "scan", "--json", "--library", "requests"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    found = residue.collect(root, json.loads(done.stdout), 10, {})
    assert found["packs"] == []
    assert found["guides"] == []
    assert found["total"] == 2
    assert found["places"][0]["reason"] == "no_pack_for_usage"
    assert found["places"][0]["context"]["text"].startswith("import requests")


def test_a_place_in_a_file_that_is_gone_has_no_window(tree: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "obelize", "scan", "--json", "--pack", PACK],
        cwd=tree,
        capture_output=True,
        check=True,
    )
    (tree / "left.py").unlink()
    commit_all(tree)
    found = residue.collect(tree, json.loads(done.stdout), 200, {})
    gone = [place for place in found["places"] if place["path"] == "left.py"]
    assert gone
    assert all(place["context"] is None for place in gone)


def test_a_notification_on_the_stream_gets_no_line_back(tree: Path) -> None:
    ask = b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
    assert _lines(_server(tree), ask) == []


def test_the_verdict_of_a_run_that_cannot_be_read_is_left_out(tree: Path) -> None:
    assert tools._verification(tree, RUN) is None


# What a hostile repository or a hostile agent can try.


def test_a_file_in_the_repository_cannot_stand_in_for_one_obelize_imports(tree: Path) -> None:
    """`python -m` puts the working directory first on the import path; `-P` does not."""
    marker = tree / "ran"
    (tree / "typer.py").write_text(
        f"import pathlib\npathlib.Path({str(marker)!r}).write_text('ran')\n", encoding="utf-8"
    )
    commit_all(tree)
    result = _call(_server(tree), "obelize_scan")
    assert result["isError"] is False
    assert not marker.exists()


def test_a_pack_is_a_known_id_and_never_a_file_the_repository_holds(tree: Path) -> None:
    pack = tree / "x" / "y"
    pack.mkdir(parents=True)
    (pack / "pack.yaml").write_text("language: python\n", encoding="utf-8")
    result = _call(_server(tree), "obelize_scan", packs=["x/y"])
    assert result["isError"] is True
    assert "which obelize does not know" in _payload(result)["error"]


def test_a_pack_directory_the_person_listed_is_known(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    packs = tmp_path / "packs"
    scaffold = runner.invoke(
        app,
        [
            "pack",
            "new",
            "acme/old-to-new",
            "--from",
            "old>=1,<2",
            "--to",
            "new>=2",
            "--guide",
            "https://example.com/g",
            "--dir",
            str(packs),
        ],
    )
    assert scaffold.exit_code == 0, scaffold.output
    (home / "obelize").mkdir(parents=True)
    (home / "obelize" / "config.yml").write_text(f"pack_dirs:\n  - {packs}\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    result = _call(_server(tree), "obelize_scan", packs=["acme/old-to-new"])
    assert result["isError"] is False
    assert _payload(result)["result"]["packs"][0]["id"] == "acme/old-to-new"


def test_a_configuration_of_the_persons_that_cannot_be_read_is_an_error_result(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / "obelize").mkdir(parents=True)
    (home / "obelize" / "config.yml").write_text("pack_dirs: 5\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    result = _call(_server(tree), "obelize_scan", packs=[PACK])
    assert result["isError"] is True


def test_trust_given_for_one_configuration_ends_when_the_agent_edits_it(tree: Path) -> None:
    machine = _server(tree, made=(RUN,), trust=True)
    assert _payload(_call(machine, "obelize_apply"))["exit_code"] == 4
    config = tree / ".obelize.yml"
    config.write_text("verify:\n  commands:\n    - touch pwned\n", encoding="utf-8")
    for name, arguments in (("obelize_apply", {}), ("obelize_verify", {"run": RUN})):
        result = _call(machine, name, **arguments)
        assert result["isError"] is True
        assert "not the file the server was started with" in _payload(result)["error"]
    assert not (tree / "pwned").exists()


def test_trust_does_not_cover_a_configuration_that_did_not_exist_when_the_server_started(
    tmp_path: Path,
) -> None:
    tree = committed(tmp_path / "repo", {"app.py": LEGACY})
    machine = _server(tree, trust=True)
    (tree / ".obelize.yml").write_text(
        "verify:\n  commands:\n    - touch pwned\n", encoding="utf-8"
    )
    result = _call(machine, "obelize_apply")
    assert result["isError"] is True


def test_without_trust_an_edited_configuration_is_not_even_looked_at(tree: Path) -> None:
    machine = _server(tree)
    (tree / ".obelize.yml").write_text(
        "verify:\n  commands:\n    - touch pwned\n", encoding="utf-8"
    )
    result = _call(machine, "obelize_scan")
    assert result["isError"] is False


def test_only_a_run_this_session_made_can_be_verified_or_undone(tree: Path) -> None:
    machine = _server(tree, trust=True)
    applied = _payload(_call(machine, "obelize_apply"))
    assert applied["run"] in machine._session.made
    # A folder the repository itself carries is a run nobody made here.
    forged = "20200101T000000Z-deadbeef"
    for name in ("obelize_verify", "obelize_undo"):
        result = _call(machine, name, run=forged)
        assert result["isError"] is True
        assert "is not a run this session made" in _payload(result)["error"]


def test_a_latest_pointer_that_is_not_text_does_not_end_the_session(tree: Path) -> None:
    (tree / ".obelize").mkdir()
    (tree / ".obelize" / "latest").write_bytes(b"\xff\xfe\x00")
    machine = _server(tree)
    result = _call(machine, "obelize_report")
    assert result["isError"] is True
    assert _payload(_call(machine, "obelize_scan"))["exit_code"] == 0
