"""A coding agent the person already has, asked as a text-only model: `claude -p` with no tools.

The agent is the person's own program, run under their own login, so what it receives goes where
that login sends it (docs/PRIVACY.md). It is started in an empty directory with every tool off, no
session saved, no MCP server, no skill and none of the person's settings (so no hook of theirs
runs), and with a fixed set of environment variables. A program that does not offer the flags
that make this so is not used. Its answer is read as the HTTP adapter's is and checked by the same
guard.
"""

from __future__ import annotations

import functools
import json
import shutil
import subprocess
import tempfile
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from obelize.models import EditProposal
from obelize.providers import base
from obelize.providers import openai_compat as adapter
from obelize.verify import redact

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

BACKENDS: Final = ("claude_code",)
PROGRAM: Final = {"claude_code": "claude"}
# What the agent is started with: every flag is one that takes a capability away.
RESTRICTIONS: Final = (
    "--print",
    "--output-format",
    "--tools",
    "--no-session-persistence",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--setting-sources",
    "--permission-mode",
    "--system-prompt",
)
TIMEOUT_S: Final = 300.0
OUTPUT_LIMIT: Final = 1 << 20
# Variables the agent may inherit: what it needs to find its login, its network and its terminal.
_KEPT_NAMES: Final = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TMPDIR", "TMP", "TEMP",
        "SYSTEMROOT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HTTP_PROXY", "HTTPS_PROXY",
        "NO_PROXY", "http_proxy", "https_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "CLOUD_ML_REGION",
    }
)  # fmt: skip
_KEPT_PREFIXES: Final = ("LC_", "XDG_", "ANTHROPIC_", "CLAUDE_", "AWS_", "GOOGLE_", "VERTEX_")


def environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The variables the agent starts with; a token for GitHub or an index is not among them."""
    return {
        name: value
        for name, value in environ.items()
        if name in _KEPT_NAMES or name.startswith(_KEPT_PREFIXES)
    }


class ClaudeCode:
    """One `ModelProvider` over the person's `claude` program; construct it through `build`."""

    def __init__(
        self, *, program: str, model: str | None, environ: Mapping[str, str], timeout_s: float
    ) -> None:
        self.program = program
        self.model = model
        self.environ = environ
        self.timeout_s = timeout_s

    def request(self, consultation: base.Consultation) -> bytes:
        return adapter.question(consultation).encode("utf-8")

    def argv(self) -> list[str]:
        return [
            self.program,
            "--print",
            "--output-format", "json",
            "--tools", "",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--setting-sources", "",
            "--permission-mode", "dontAsk",
            "--system-prompt", adapter.SYSTEM_PROMPT,
            *(["--model", self.model] if self.model else []),
        ]  # fmt: skip

    def propose(self, consultation: base.Consultation) -> base.Reply:
        """Ask once; answer with a proposal, with nothing, or by raising."""
        with tempfile.TemporaryDirectory(prefix="obelize-agent-") as empty:
            try:
                done = subprocess.run(
                    self.argv(),
                    input=self.request(consultation),
                    capture_output=True,
                    cwd=empty,
                    env=environment(self.environ),
                    timeout=self.timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise self._failure(
                    "endpoint_unreachable", f"no answer within {self.timeout_s:g} s"
                ) from error
            except OSError as error:
                raise self._failure("endpoint_unreachable", str(error)) from error
        if len(done.stdout) > OUTPUT_LIMIT:
            raise self._failure("response_too_large", f"more than {OUTPUT_LIMIT} bytes")
        try:
            data = json.loads(done.stdout)
        except (ValueError, RecursionError) as error:
            said = done.stderr.decode("utf-8", "replace").strip() or str(error)
            raise self._failure("response_not_json", said) from error
        if not isinstance(data, dict) or done.returncode != 0 or data.get("is_error"):
            raise self._failure("endpoint_refused", adapter._shown(data))
        content = data.get("result")
        if not isinstance(content, str):
            raise self._failure("response_not_a_completion", adapter._shown(data))
        usage = data["usage"] if isinstance(data.get("usage"), dict) else {}
        tokens_in = _count(usage, "input_tokens") + _count(usage, "cache_creation_input_tokens")
        tokens_in += _count(usage, "cache_read_input_tokens")
        tokens_out = _count(usage, "output_tokens")
        answer = adapter._object(content)
        if answer is None:
            raise self._failure("answer_not_json", content)
        if "proposal" not in answer:
            raise self._failure("answer_not_a_proposal", f"no proposal key in {sorted(answer)}")
        found = answer["proposal"]
        if found is None:
            return base.Reply(None, tokens_in, tokens_out, adapter.unchanged_reason(answer))
        if not isinstance(found, dict):
            raise self._failure("answer_not_a_proposal", f"proposal is a {type(found).__name__}")
        try:
            return base.Reply(EditProposal.model_validate(found), tokens_in, tokens_out)
        except ValidationError as error:
            raise self._failure("proposal_does_not_hold", str(error)) from error

    def _failure(self, failure: Any, detail: str) -> base.ProviderError:
        said = adapter._short(redact.redact(detail, self.environ))
        return base.ProviderError(failure, said.encode("utf-8", "backslashreplace").decode("utf-8"))


def build(
    backend: str, model: str | None, environ: Mapping[str, str], *, timeout_s: float = TIMEOUT_S
) -> ClaudeCode:
    """The agent for `backend`, or `ProviderError` saying why it cannot be a text-only model."""
    program = shutil.which(PROGRAM[backend], path=environ.get("PATH"))
    if program is None:
        raise base.ProviderError(
            "endpoint_unreachable", f"{PROGRAM[backend]} is not on PATH, so it cannot be asked"
        )
    if program.lower().endswith((".cmd", ".bat")):  # pragma: windows-only
        raise base.ProviderError(
            "endpoint_unreachable",
            f"{program} is a batch file, whose quoting obelize will not trust",
        )
    missing = unsupported(program, tuple(sorted(environment(environ).items())))
    if missing:
        raise base.ProviderError(
            "endpoint_unreachable",
            f"{program} does not offer {', '.join(missing)}, so it cannot be held to a text answer",
        )
    return ClaudeCode(program=program, model=model, environ=environ, timeout_s=timeout_s)


@functools.cache
def unsupported(program: str, environ: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    """The restrictions `program --help` does not mention, once per program."""
    try:
        done = subprocess.run(
            [program, "--help"],
            capture_output=True,
            env=dict(environ),
            timeout=30,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return RESTRICTIONS
    text = done.stdout.decode("utf-8", "replace")
    return tuple(flag for flag in RESTRICTIONS if flag not in text)


def _count(usage: Mapping[str, Any], key: str) -> int:
    value = usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


__all__ = ["BACKENDS", "ClaudeCode", "build", "environment"]
