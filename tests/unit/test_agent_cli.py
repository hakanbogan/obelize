"""`providers.agent_cli`: the person's coding agent, asked as a text-only model."""

from __future__ import annotations

import json
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from obelize.models import EditProposal
from obelize.providers import agent_cli, base
from obelize.providers import openai_compat as adapter
from platforms import posix_only

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = posix_only("the fake agent is an executable script")

PROPOSAL = {
    "path": "app.py",
    "start_line": 5,
    "end_line": 5,
    "symbol": "acme_kit.old_greet",
    "replaces": "    return acme_kit.old_greet(name)",
    "replacement": "    return acme_kit.greet(name)",
    "rationale": "The library renamed it.",
}


def consultation() -> base.Consultation:
    context = base.Context(
        "app.py",
        1,
        5,
        "import acme_kit\n\n\ndef hello(name):\n    return acme_kit.old_greet(name)\n",
    )
    return base.Consultation(
        context, 5, 11, "acme_kit.old_greet", "flag_only_surface", "acme-kit/1-0-to-2-0",
        "acme-kit", ("acme_kit",), (), note="Renamed in acme-kit 2.0: use greet.",
    )  # fmt: skip


def fake(
    tmp_path: Path,
    *,
    answer: object = None,
    exit_code: int = 0,
    hide: str = "",
    sleep: float = 0.0,
    raw: str | None = None,
) -> dict[str, str]:
    """A `claude` on PATH that records how it was started and answers as the test says."""
    folder = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    record = tmp_path / "record.json"
    body = json.dumps(
        {
            "result": json.dumps(answer),
            "usage": {
                "input_tokens": 3,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 7,
                "output_tokens": 9,
            },
        }
        if raw is None
        else None
    )
    script = folder / "claude"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json, os, sys, time
            if "--help" in sys.argv:
                every = {list(agent_cli.RESTRICTIONS)!r}
                print("Usage: claude " + " ".join(f for f in every if f != {hide!r}))
                sys.exit(0)
            seen = {{"argv": sys.argv[1:], "cwd": os.getcwd(), "env": sorted(os.environ)}}
            seen["stdin"] = sys.stdin.read()
            open({str(record)!r}, "w").write(json.dumps(seen))
            time.sleep({sleep})
            sys.stdout.write({raw!r} if {raw is not None!r} else {body!r})
            sys.exit({exit_code})
            """
        )
    )
    script.chmod(0o755)
    return {
        "PATH": str(folder),
        "HOME": str(tmp_path),
        "GITHUB_TOKEN": "ghp_secret",
        "ANTHROPIC_API_KEY": "sk-ant",
        "LC_ALL": "C",
        "PYTHONPATH": "x",
    }


def agent(environ: dict[str, str], timeout_s: float = 20.0) -> agent_cli.ClaudeCode:
    return agent_cli.build("claude_code", "sonnet", environ, timeout_s=timeout_s)


def test_the_agent_is_started_with_every_capability_taken_away_in_an_empty_directory(
    tmp_path: Path,
) -> None:
    environ = fake(tmp_path, answer={"proposal": PROPOSAL})
    reply = agent(environ).propose(consultation())
    assert reply.proposal == EditProposal.model_validate(PROPOSAL)
    assert (reply.tokens_in, reply.tokens_out) == (110, 9)
    seen = json.loads((tmp_path / "record.json").read_text())
    argv = seen["argv"]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--system-prompt") + 1] == adapter.SYSTEM_PROMPT
    assert argv[argv.index("--model") + 1] == "sonnet"
    for flag in (
        "--print",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--disable-slash-commands",
    ):
        assert flag in argv
    assert seen["stdin"] == adapter.question(consultation())
    assert "what the pack says about it: Renamed in acme-kit 2.0: use greet." in seen["stdin"]
    assert not seen["cwd"].startswith(str(tmp_path / "repo"))
    assert "GITHUB_TOKEN" not in seen["env"]
    assert "PYTHONPATH" not in seen["env"]
    assert {"PATH", "HOME", "ANTHROPIC_API_KEY", "LC_ALL"} <= set(seen["env"])
    assert agent(environ).request(consultation()) == adapter.question(consultation()).encode()


def test_no_proposal_is_an_answer(tmp_path: Path) -> None:
    reply = agent(fake(tmp_path, answer={"proposal": None})).propose(consultation())
    assert reply.proposal is None


@pytest.mark.parametrize(
    ("kwargs", "failure"),
    [
        ({"answer": {"nothing": 1}}, "answer_not_a_proposal"),
        ({"answer": {"proposal": 3}}, "answer_not_a_proposal"),
        ({"answer": {"proposal": {"path": 1}}}, "proposal_does_not_hold"),
        ({"answer": "not an object"}, "answer_not_json"),
        ({"raw": "not json"}, "response_not_json"),
        ({"raw": json.dumps({"is_error": True, "result": "overloaded"})}, "endpoint_refused"),
        ({"raw": json.dumps({"result": 7})}, "response_not_a_completion"),
        ({"raw": "[]"}, "endpoint_refused"),
        ({"answer": {"proposal": None}, "exit_code": 2}, "endpoint_refused"),
        ({"raw": "x" * (agent_cli.OUTPUT_LIMIT + 1)}, "response_too_large"),
    ],
)
def test_an_answer_that_is_not_a_proposal_is_a_failure_word(
    tmp_path: Path, kwargs: dict[str, object], failure: str
) -> None:
    with pytest.raises(base.ProviderError) as raised:
        agent(fake(tmp_path, **kwargs)).propose(consultation())  # type: ignore[arg-type]
    assert raised.value.failure == failure


def test_an_agent_that_does_not_answer_in_time_is_unreachable(tmp_path: Path) -> None:
    with pytest.raises(base.ProviderError) as raised:
        agent(fake(tmp_path, answer={"proposal": None}, sleep=5), timeout_s=0.5).propose(
            consultation()
        )
    assert raised.value.failure == "endpoint_unreachable"
    assert "no answer within" in raised.value.detail


def test_an_agent_that_cannot_be_started_is_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = agent(fake(tmp_path, answer={"proposal": None}))
    (tmp_path / "bin" / "claude").unlink()
    with pytest.raises(base.ProviderError) as raised:
        provider.propose(consultation())
    assert raised.value.failure == "endpoint_unreachable"


def test_a_program_that_is_not_there_or_lacks_a_restriction_is_not_used(
    tmp_path: Path,
) -> None:
    with pytest.raises(base.ProviderError, match="not on PATH"):
        agent_cli.build("claude_code", None, {"PATH": str(tmp_path)})
    (tmp_path / "other").mkdir()
    environ = fake(tmp_path / "other", answer=None, hide="--tools")
    with pytest.raises(base.ProviderError, match=r"does not offer --tools"):
        agent_cli.build("claude_code", None, environ)


def test_a_program_whose_help_does_not_run_offers_nothing() -> None:
    agent_cli.unsupported.cache_clear()
    assert agent_cli.unsupported("/no/such/claude", ()) == agent_cli.RESTRICTIONS
