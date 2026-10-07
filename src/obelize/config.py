"""`.obelize.yml`: reading it, merging the flags over it, and choosing files.

The always-excluded set (led by `.obelize/`, so a scan never grades its own report) is matched
first and cannot be undone; `include` applies before any read. Flags beat the file, and loading
executes nothing and reads only `<repo>/.obelize.yml`. Any unusable file raises `ConfigError`.
"""

from __future__ import annotations

import difflib
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pathspec
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from obelize import _yaml
from obelize.models import (
    Config,
    ConfiguredCommand,
    ModelConfig,
    VerifyConfig,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pydantic_core import ErrorDetails

# The only name read; a `.obelize.yaml` is refused by name rather than silently ignored.
CONFIG_FILENAME = ".obelize.yml"
MISTAKEN_FILENAME = ".obelize.yaml"

# Paths no configuration can bring back; tests/unit/test_config.py holds it equal to docs/CLI.md.
# `site-packages/` catches a virtual environment whatever it is called.
ALWAYS_EXCLUDED: tuple[str, ...] = (
    ".obelize/",
    ".*/",
    "__pycache__/",
    "site-packages/",
    "venv/",
    "node_modules/",
    "vendor/",
    "_vendor/",
    "build/",
    "dist/",
    "*.egg-info/",
)

# What `run.json` records as `config.source`.
ConfigSource = Literal["file", "defaults"]

# `excluded` (the user's own `exclude`) is reported by name: those files' imports still break
# when the legacy pin is dropped.
Decision = Literal["selected", "always_excluded", "excluded", "not_included"]


class ConfigError(Exception):
    """Unusable `.obelize.yml` or flags; the message never shows an absolute path (CI logs)."""


class Overrides(BaseModel):
    """The only flags that overlap `.obelize.yml`; the others are per-run choices."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verify_commands: tuple[ConfiguredCommand, ...] = ()
    timeout_s: int | None = Field(default=None, gt=0)
    allow_dirty: bool = False


class LoadedConfig(BaseModel):
    """A configuration and its source, which the evidence records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    config: Config
    source: ConfigSource


def documented_keys(model: type[BaseModel] = Config) -> tuple[str, ...]:
    """Every key `.obelize.yml` accepts, dotted, in order; a test holds it equal to docs/CLI.md."""
    keys: list[str] = []
    for name, field in model.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            keys.extend(f"{name}.{child}" for child in documented_keys(annotation))
        else:
            keys.append(name)
    return tuple(keys)


def _yaml_message(error: yaml.YAMLError) -> str:
    """A YAML failure as line and column, when the parser knows them."""
    located = _yaml.where(error)
    if located is None:
        return f"{CONFIG_FILENAME} is not valid YAML: {' '.join(str(error).split())}"
    line, column, problem = located
    return f"{CONFIG_FILENAME}:{line}:{column}: {problem}"


def _said(item: ErrorDetails) -> str:
    """One pydantic error in the validator's own words, without the `Value error, ` it adds."""
    return item["msg"].removeprefix("Value error, ")


def _problems(error: ValidationError, schema: type[BaseModel]) -> list[str]:
    """A pydantic error report, rewritten as the keys a person wrote."""
    known = documented_keys(schema)
    lines: list[str] = []
    for item in error.errors():
        key = ".".join(str(part) for part in item["loc"])
        if item["type"] == "extra_forbidden":
            parent, _, leaf = key.rpartition(".")
            siblings = [
                candidate.rpartition(".")[2]
                for candidate in known
                if candidate.rpartition(".")[0] == parent
            ]
            close = difflib.get_close_matches(leaf, siblings, n=1, cutoff=0.6)
            suggestion = f"; did you mean {close[0]!r}?" if close else ""
            lines.append(f"unknown key {key!r}{suggestion}")
        else:
            lines.append(f"{key}: {_said(item)}" if key else _said(item))
    return lines


def refusal(error: ValidationError, heading: str, schema: type[BaseModel] = Config) -> ConfigError:
    """A file's refusal: the heading, then each problem under the key it is about.

    A misspelt key is matched against `schema`'s keys, the file's own.
    """
    lines = _problems(error, schema)
    return ConfigError("\n".join([heading, *(f"  - {line}" for line in lines)]))


def _spec(patterns: Sequence[str], field: str) -> pathspec.PathSpec[pathspec.Pattern]:
    """`GitIgnoreSpec`, not the plain factory: like git, `legacy/*` excludes `legacy/sub/x.py`."""
    try:
        return pathspec.GitIgnoreSpec.from_lines(patterns)
    except ValueError as error:
        raise ConfigError(f"{CONFIG_FILENAME}: {field} is not a usable pattern: {error}") from error


def _relative(path: str) -> str:
    """Require a repository-relative posix path; an absolute one would silently never match."""
    if not path:
        raise ValueError("a path to match must not be empty")
    if path.startswith("/"):
        raise ValueError(f"a path to match is relative to the repository root, got {path!r}")
    if "\\" in path:
        raise ValueError(f"a path to match uses forward slashes on every platform, got {path!r}")
    return path


class Selection:
    """Which repository-relative paths a scan may look at; pure path arithmetic, no filesystem."""

    __slots__ = ("_always", "_exclude", "_include")

    def __init__(self, config: Config) -> None:
        self._always = _spec(ALWAYS_EXCLUDED, "the always-excluded set")
        self._exclude = _spec(config.exclude, "exclude")
        self._include = _spec((config.include,), "include")

    def decide(self, path: str) -> Decision:
        """Whether the scan looks at `path`, and which rule decided it.

        `excluded` only when the user's `exclude` removed a file `include` selected.
        """
        candidate = _relative(path)
        if self._always.match_file(candidate):
            return "always_excluded"
        if not self._include.match_file(candidate):
            return "not_included"
        return "excluded" if self._exclude.match_file(candidate) else "selected"

    def selects(self, path: str) -> bool:
        return self.decide(path) == "selected"

    def selects_manifest(self, path: str) -> bool:
        """Whether the scan reads `path` as a dependency manifest.

        Ignores `include` (the default `**/*.py` would drop every manifest), not `exclude`.
        """
        candidate = _relative(path)
        return not self._always.match_file(candidate) and not self._exclude.match_file(candidate)

    def prunes_directory(self, path: str) -> bool:
        """Whether a directory can be skipped whole, without looking inside.

        Never for the user's `exclude`: the report must name excluded files that still import the
        legacy distribution.
        """
        return bool(self._always.match_file(_relative(path).rstrip("/") + "/"))


def load(repo: Path) -> LoadedConfig:
    """Read `<repo>/.obelize.yml`, or return the documented defaults.

    Only an absent file means defaults; a denied `lstat` raises (`Path.exists` hides it on 3.14).
    """
    path = repo / CONFIG_FILENAME
    if _absent(path):
        if os.path.isfile(repo / MISTAKEN_FILENAME):
            raise ConfigError(
                f"{MISTAKEN_FILENAME} is not read; the configuration file is "
                f"{CONFIG_FILENAME}. Rename it so its settings apply."
            )
        return LoadedConfig(config=Config(), source="defaults")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ConfigError(
            f"{CONFIG_FILENAME} is not UTF-8: {error.reason} at byte {error.start}"
        ) from error
    except OSError as error:
        raise ConfigError(f"{CONFIG_FILENAME} cannot be read: {error.strerror}") from error
    data = _parse(text)
    if "model" in data:
        raise ConfigError(
            f"{CONFIG_FILENAME}: model settings are not read from a repository, because they "
            f"decide where your code and API key are sent. Put the model block in "
            f"~/.config/obelize/config.yml, or pass --model."
        )
    if "pack_dirs" in data:
        raise ConfigError(
            f"{CONFIG_FILENAME}: pack directories are not read from a repository, because a pack "
            f"decides what obelize writes. Put pack_dirs in ~/.config/obelize/config.yml, or pass "
            f"--pack."
        )
    try:
        config = Config.model_validate(data)
    except ValidationError as error:
        raise refusal(error, f"{CONFIG_FILENAME} is not valid:") from error
    # Compile now: an unusable `exclude` is a ConfigError, not a traceback mid-walk.
    Selection(config)
    return LoadedConfig(config=config, source="file")


def _absent(path: Path) -> bool:
    """Whether nothing is at `path`, raising when the filesystem will not say."""
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError as error:
        raise ConfigError(f"{CONFIG_FILENAME} cannot be read: {error.strerror}") from error
    return False


def _parse(text: str) -> dict[str, Any]:
    try:
        data = _yaml.parse(text)
    except _yaml.DuplicateKeyError as error:
        raise ConfigError(
            f"{CONFIG_FILENAME}:{error.line}: {error}. "
            f"YAML keeps the last one and discards the first."
        ) from error
    except yaml.YAMLError as error:
        raise ConfigError(_yaml_message(error)) from error
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"{CONFIG_FILENAME} holds a mapping of settings at the top level, "
            f"and this one holds a {type(data).__name__}"
        )
    return data


def flags(verify_commands: Sequence[str], timeout_s: int | None, *, allow_dirty: bool) -> Overrides:
    """The flags that overlap the file, refused as the file's own values would be."""
    try:
        return Overrides(
            verify_commands=tuple(verify_commands), timeout_s=timeout_s, allow_dirty=allow_dirty
        )
    except ValidationError as error:
        # typer refuses a `--timeout` below 1, so only a `--verify` gets here.
        raise ConfigError(
            "\n".join(f"--verify is not valid: {_said(item)}" for item in error.errors())
        ) from error


def merge(config: Config, overrides: Overrides) -> Config:
    """Apply the command line over the file; the command line wins.

    `--verify` replaces the file's list, never appends, so every command is then user-typed.
    A boolean flag can only turn a setting on.
    """
    # Inputs are validated at their source and no cross-field rule exists, so this cannot raise.
    return Config(
        include=config.include,
        exclude=config.exclude,
        verify=VerifyConfig(
            commands=overrides.verify_commands or config.verify.commands,
            timeout_s=(
                config.verify.timeout_s if overrides.timeout_s is None else overrides.timeout_s
            ),
            junit=config.verify.junit,
        ),
        allow_dirty=config.allow_dirty or overrides.allow_dirty,
        max_file_bytes=config.max_file_bytes,
    )


def model(user: ModelConfig, provider: str | None, read: Path) -> ModelConfig:
    """The user's `model:` block, read from `read`, with `--model` over it, re-validated so a bad
    pair fails here.

    `load` refuses a repository `model:`.
    """
    fields = user.model_dump()
    if provider is not None:
        fields["provider"] = provider
    try:
        return ModelConfig.model_validate(fields)
    except ValidationError as error:
        raise refusal(
            error, f"--model {provider} with the model block in {read} is not valid:"
        ) from error


__all__ = [
    "ALWAYS_EXCLUDED",
    "CONFIG_FILENAME",
    "MISTAKEN_FILENAME",
    "ConfigError",
    "ConfigSource",
    "Decision",
    "LoadedConfig",
    "Overrides",
    "Selection",
    "documented_keys",
    "flags",
    "load",
    "merge",
    "model",
    "refusal",
]
