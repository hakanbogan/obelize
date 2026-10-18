"""Whether a verification command may run (the trust ladder), and running it.

Kept in one module so the policy sits beside the execution mechanics that bound it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    ValidationError,
    field_validator,
)

from obelize import _yaml, net
from obelize.config import ConfigError, refusal
from obelize.models import CommandResult, CommandSource, ConfiguredCommand, ModelConfig
from obelize.native import processes
from obelize.verify import redact

# User-level files, never read from a checkout, so a repository cannot grant itself trust.
# `$XDG_CONFIG_HOME` is honoured, as `~/.config` is its default.
CONFIG_DIRNAME = "obelize"
ALLOWLIST_FILENAME = "config.yml"
APPROVALS_FILENAME = "approved.json"

# Set for every command so a suite can tell obelize ran it; the rest, credentials included, is
# inherited.
OBELIZE_RUN = "OBELIZE_RUN"

# Seconds from SIGTERM to SIGKILL on POSIX, and of reading on after a kill or the command's exit.
GRACE_S = 5.0
DRAIN_S = 5.0

# Seconds between checks for the command's own exit.
POLL_S = 0.1

CHUNK = 64 * 1024


class _UserVerify(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allow: tuple[ConfiguredCommand, ...] = ()


class _UserNetwork(BaseModel):
    """Which index a command that reads releases asks, and whether it may ask at all.

    Only the user says: an index decides which code obelize reads, so a repository never does.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: StrictStr = "https://pypi.org"
    offline: StrictBool = False

    @field_validator("index")
    @classmethod
    def _address(cls, value: str) -> str:
        return net.index_url(value)


class UserConfig(BaseModel):
    """`~/.config/obelize/config.yml`: the settings no repository may make.

    Deliberately not a default for `.obelize.yml`, or a repository could set its allowlist or model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    verify: _UserVerify = Field(default_factory=_UserVerify)
    model: ModelConfig = Field(default_factory=ModelConfig)
    network: _UserNetwork = Field(default_factory=_UserNetwork)
    # Where more migration packs live. A pack decides what is written and which imports a model may
    # add, so only the user names them: a repository never does.
    pack_dirs: tuple[StrictStr, ...] = ()

    @field_validator("pack_dirs")
    @classmethod
    def _directories(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        expanded = tuple(os.path.expanduser(entry) for entry in value)
        for entry in expanded:
            if not os.path.isabs(entry) or not os.path.isdir(entry):
                raise ValueError(
                    f"{entry!r} is not an existing directory given as an absolute path"
                )
        return expanded


@dataclass(frozen=True, slots=True)
class Mode:
    """What this machine and invocation look like to the trust ladder.

    `tty` is passed in; only `obelize.cli` asks the terminal. `CI` counts when set, even to empty.
    """

    non_interactive: bool = False
    trust_repo_config: bool = False
    ci: bool = False
    tty: bool = False

    @classmethod
    def of(
        cls,
        environ: Mapping[str, str],
        *,
        non_interactive: bool = False,
        trust_repo_config: bool = False,
        tty: bool = False,
    ) -> Mode:
        return cls(
            non_interactive=non_interactive,
            trust_repo_config=trust_repo_config,
            ci="CI" in environ,
            tty=tty,
        )

    @property
    def interactive(self) -> bool:
        return self.tty and not self.ci and not self.non_interactive


@dataclass(frozen=True, slots=True)
class Command:
    """One command, its rung, and its argv; the allowlist matches argv, not text."""

    text: str
    source: CommandSource
    argv: tuple[str, ...]

    @classmethod
    def of(cls, text: str, source: CommandSource) -> Command:
        return cls(text=text, source=source, argv=tuple(shlex.split(text)))


@dataclass(frozen=True, slots=True)
class Allowed:
    """Every command may run, each recorded under its rung."""

    commands: tuple[Command, ...] = ()


@dataclass(frozen=True, slots=True)
class Refused:
    """One command may not, so none runs; `command` is the text displayed."""

    command: str


def config_home(environ: Mapping[str, str]) -> Path:
    """The user's directory; a relative `XDG_CONFIG_HOME` is invalid, and ignored as the spec says.

    Followed, it would name a directory under wherever the command runs, which can be a repository,
    and a repository does not choose the model, the allowlist or the pack directories.
    """
    base = environ.get("XDG_CONFIG_HOME")
    if base and Path(base).is_absolute():
        return Path(base) / CONFIG_DIRNAME
    return Path(environ.get("HOME", "~")).expanduser() / ".config" / CONFIG_DIRNAME


def user_config(config_dir: Path) -> UserConfig:
    """`config.yml`, or defaults when absent; unlike `approvals`, a bad file raises.

    Ignoring it would silently drop the user's commands or model; a lost approval costs a prompt.
    """
    path = config_dir / ALLOWLIST_FILENAME
    try:
        with path.open("rb") as handle:
            raw = handle.read(_yaml.MAX_BYTES + 1)
        if len(raw) > _yaml.MAX_BYTES:
            raise ConfigError(f"{path} is larger than {_yaml.MAX_BYTES >> 20} MiB")
        text = raw.decode("utf-8")
    except FileNotFoundError:
        return UserConfig()
    except UnicodeDecodeError as error:
        raise ConfigError(f"{path} is not UTF-8: {error.reason} at byte {error.start}") from error
    except OSError as error:
        raise ConfigError(f"{path} cannot be read: {error.strerror}") from error
    try:
        data = _yaml.parse(text)
    except _yaml.DuplicateKeyError as error:
        raise ConfigError(f"{path}:{error.line}: {error}") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"{path} is not valid YAML: {error}") from error
    if data is None:
        return UserConfig()
    try:
        return UserConfig.model_validate(data)
    except ValidationError as error:
        raise refusal(error, f"{path} is not valid:", UserConfig) from error


def allowlist(config_dir: Path) -> frozenset[tuple[str, ...]]:
    return frozenset(
        tuple(shlex.split(command)) for command in user_config(config_dir).verify.allow
    )


def digest(command: str) -> str:
    """An approval's key: the text the user was shown, not the argv."""
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def approvals(config_dir: Path) -> frozenset[tuple[str, str]]:
    """The approved `(repository, sha256)` pairs; an unreadable store fails closed, to empty."""
    return frozenset((row["repo"], row["sha256"]) for row in _stored(config_dir))


def _stored(config_dir: Path) -> list[dict[str, Any]]:
    """The rows of the store as they are written, those that name a repository and a hash."""
    try:
        data: Any = json.loads((config_dir / APPROVALS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("approvals"), list):
        return []
    return [
        row
        for row in data["approvals"]
        if isinstance(row, dict)
        and isinstance(row.get("repo"), str)
        and isinstance(row.get("sha256"), str)
    ]


def remember(config_dir: Path, repository: str, command: str) -> None:
    """Append one approval atomically (temporary file, rename), keeping every row as it is.

    The rows already there keep the command text they were given, which says what was approved.
    0700 and 0600, from the first byte: a store another account can append to is an allowlist it
    maintains.
    """
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = config_dir / APPROVALS_FILENAME
    rows = _stored(config_dir)
    key = {"repo": repository, "sha256": digest(command)}
    if (repository, key["sha256"]) not in approvals(config_dir):
        rows.append({**key, "command": command})
    temporary = path.with_name(f"{APPROVALS_FILENAME}.{os.getpid()}.tmp")
    document = json.dumps({"version": 1, "approvals": rows}, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(document)
    temporary.chmod(0o600)
    os.replace(temporary, path)


def resolve(
    root: Path,
    *,
    mode: Mode,
    config_dir: Path,
    cli_commands: Sequence[str] = (),
    repo_commands: Sequence[str] = (),
    ask: Callable[[str], bool] | None = None,
) -> Allowed | Refused:
    """The trust ladder, top down, over one run's commands.

    Any `--verify` replaces the repository's list, so no trust decision is taken. One refusal
    refuses the phase: a `pass` over half the commands would read as a full one.
    """
    if cli_commands:
        return Allowed(tuple(Command.of(text, "cli") for text in cli_commands))
    if not repo_commands:
        return Allowed()
    permitted = allowlist(config_dir)
    remembered = approvals(config_dir)
    repository = str(root.resolve())
    chosen: list[Command] = []
    for text in repo_commands:
        command = Command.of(text, "repo_config")
        if command.argv in permitted:
            chosen.append(replace(command, source="user_allowlist"))
            continue
        if mode.trust_repo_config or (repository, digest(text)) in remembered:
            chosen.append(command)
            continue
        if not mode.interactive or ask is None or not ask(text):
            return Refused(text)
        remember(config_dir, repository, text)
        chosen.append(command)
    return Allowed(tuple(chosen))


def run(
    root: Path,
    commands: Iterable[Command],
    *,
    timeout_s: int,
    environ: Mapping[str, str],
    junit_dir: Path | None = None,
) -> tuple[CommandResult, ...]:
    """Every command in order, each with its own deadline; all run even after one fails."""
    return tuple(
        execute(
            root,
            command,
            timeout_s=timeout_s,
            environ=environ,
            junit_dir=junit_dir,
            index=index,
        )
        for index, command in enumerate(commands, start=1)
    )


def execute(
    root: Path,
    command: Command,
    *,
    timeout_s: int,
    environ: Mapping[str, str],
    junit_dir: Path | None = None,
    index: int = 1,
) -> CommandResult:
    """One command under the trust ladder's mechanics.

    No shell (a `|` is an argument); stdin at EOF so a prompt cannot hang; a new session, or on
    Windows a job, so the deadline reaches every child; output redacted before it can reach a
    run folder.
    """
    argv, junit = _argv(command, junit_dir, index)
    environment = {**environ, OBELIZE_RUN: "1"}
    shown = _shown(command, environment)
    started = time.monotonic()
    try:
        process = processes.spawn(argv, root, environment)
    except OSError as error:
        return CommandResult(
            command=shown,
            source=command.source,
            status="inconclusive",
            reason="command_not_executable",
            exit_code=None,
            duration_ms=_ms(started),
            output=redact.redact(f"{argv[0]}: {error}", environment),
        )
    try:
        deadline = started + timeout_s
        head, tail, elided, timed_out = _drain(process, deadline)
        if not timed_out and not _reaped(process, deadline):
            _kill(process)
            timed_out = True
        code = process.wait()
    finally:
        processes.close(process)
    text, truncated = redact.cap(head, tail, elided)
    produced = _produced(junit_dir, junit)
    return CommandResult(
        command=shown,
        source=command.source,
        status="inconclusive" if timed_out else ("pass" if code == 0 else "fail"),
        reason="timeout" if timed_out else (None if code == 0 else "command_failed"),
        exit_code=code,
        duration_ms=_ms(started),
        output=redact.redact(text, environment),
        truncated=truncated,
        junit=produced,
        in_obelize_environment=_ours(argv[0], environment),
    )


def _shown(command: Command, environment: Mapping[str, str]) -> str:
    """What is recorded: a credential typed into the command must not outlive the run.

    The record must still split into arguments. A match that crossed a quote (a PEM block, or a
    secret value holding one) leaves the program and `[REDACTED]` instead.
    """
    shown = redact.redact(command.text, environment)
    try:
        shlex.split(shown)
    except ValueError:
        program = redact.redact(shlex.split(command.text)[0], environment)
        return f"{shlex.quote(program)} {redact.REDACTED}"
    return shown


def _ours(program: str, environment: Mapping[str, str]) -> bool:
    """Whether `PATH` resolves a bare `program` inside `sys.prefix`, as under `uv run obelize`."""
    found = processes.locate(program, environment)
    return found is not None and Path(found).is_relative_to(sys.prefix)


def _produced(junit_dir: Path | None, junit: str | None) -> str | None:
    """The junit name if the command really wrote it; no row may point at a missing file."""
    if junit_dir is None or junit is None:
        return None
    return junit if (junit_dir / junit).exists() else None


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _argv(
    command: Command, junit_dir: Path | None, index: int
) -> tuple[tuple[str, ...], str | None]:
    """The argv, plus `--junitxml` for a pytest command that lacks one, and that junit name."""
    if junit_dir is None or not _is_pytest(command.argv) or _carries_junit(command.argv):
        return command.argv, None
    name = f"{index}.junit.xml"
    return (*command.argv, f"--junitxml={junit_dir / name}"), name


def _is_pytest(argv: tuple[str, ...]) -> bool:
    first = processes.program_name(argv[0])
    return first in ("pytest", "py.test") or (
        first.startswith("python") and argv[1:3] == ("-m", "pytest")
    )


def _carries_junit(argv: tuple[str, ...]) -> bool:
    return any(word == "--junitxml" or word.startswith("--junitxml=") for word in argv)


def _drain(process: subprocess.Popen[bytes], deadline: float) -> tuple[bytes, bytes, int, bool]:
    """Read to EOF or the deadline, keeping head and tail and counting the elided middle.

    The deadline is checked around the read: waiting first deadlocks on a full pipe, and EOF is not
    the command's end. After it exits (a leftover server may hold the pipe), read up to `DRAIN_S`,
    kill its group, keep its exit code. Past the deadline it times out: kill, read `DRAIN_S` more.
    """
    stream = process.stdout
    if stream is None:  # pragma: no cover - `spawn` opens a pipe, so it never is
        raise RuntimeError("the process was started without a pipe")
    head, tail, elided, timed_out = bytearray(), bytearray(), 0, False
    ended: float | None = None
    while True:
        now = time.monotonic()
        # After a kill the second deadline ends the read even if the group survives.
        if ended is None and not timed_out and process.poll() is not None:
            ended = now
        if ended is not None and now >= min(deadline, ended + DRAIN_S):
            processes.end(process.pid)
            break
        remaining = deadline - now
        if remaining <= 0:
            if timed_out:
                break
            _kill(process)
            timed_out = True
            deadline = time.monotonic() + DRAIN_S
            continue
        chunk = processes.read(stream, CHUNK, min(remaining, POLL_S))
        if chunk is None:
            continue
        if not chunk:
            break
        room = redact.HEAD_BYTES - len(head)
        if room > 0:
            head += chunk[:room]
            chunk = chunk[room:]
        tail += chunk
        if len(tail) > redact.TAIL_BYTES:
            elided += len(tail) - redact.TAIL_BYTES
            del tail[: len(tail) - redact.TAIL_BYTES]
    stream.close()
    return bytes(head), bytes(tail), elided, timed_out


def _reaped(process: subprocess.Popen[bytes], deadline: float) -> bool:
    try:
        process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        return False
    return True


def _kill(process: subprocess.Popen[bytes]) -> None:
    processes.stop(process, GRACE_S)


__all__ = [
    "ALLOWLIST_FILENAME",
    "APPROVALS_FILENAME",
    "CONFIG_DIRNAME",
    "GRACE_S",
    "OBELIZE_RUN",
    "Allowed",
    "Command",
    "Mode",
    "Refused",
    "UserConfig",
    "allowlist",
    "approvals",
    "config_home",
    "digest",
    "execute",
    "remember",
    "resolve",
    "run",
    "user_config",
]
