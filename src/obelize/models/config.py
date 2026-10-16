"""The configuration after the merge of `.obelize.yml` and the flags: verification, model
and scan settings."""

from __future__ import annotations

import ipaddress
import re
from typing import Final
from urllib.parse import urlsplit

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from obelize.models.fields import ConfiguredCommand, _Frozen
from obelize.models.vocabulary import DEFAULT_INCLUDE, ProviderName

# The user config names the variable holding the API key, never the key; a pasted `sk-...` key
# fails because `-` is not a name character.
_ENV_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _loopback(host: str) -> bool:
    """`localhost` or a loopback address by its text; a name that resolves to one is not."""
    try:
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# Seconds a verification command may run when neither `verify.timeout_s` nor `--timeout` says.
TIMEOUT_S: Final = 600


class VerifyConfig(_Frozen):
    """`verify:` in `.obelize.yml`.

    Listing a command does not trust it: it is confirmed interactively and refused under
    `--non-interactive` or CI unless allowlisted or `--trust-repo-config` is passed.
    Deliberately neither sorted nor de-duplicated: the list is a script.
    """

    commands: tuple[ConfiguredCommand, ...] = ()
    timeout_s: StrictInt = Field(default=TIMEOUT_S, gt=0)
    junit: StrictBool = True


class ModelConfig(_Frozen):
    """`model:` in the user's own `~/.config/obelize/config.yml`, and nowhere else.

    A repository's `.obelize.yml` may not set it: where code and a credential are
    sent is the runner's choice, not the migrated code's.
    """

    provider: ProviderName = "none"
    base_url: str | None = None
    allow_insecure_http: bool = False
    model: str | None = None
    api_key_env: str = "OBELIZE_MODEL_API_KEY"
    log_prompts: bool = False

    @model_validator(mode="after")
    def _check(self) -> ModelConfig:
        if not _ENV_VAR_NAME.fullmatch(self.api_key_env):
            raise ValueError(
                f"api_key_env names the environment variable that holds the key, not the "
                f"key: {self.api_key_env!r} is not a variable name"
            )
        if self.base_url is not None:
            parts = urlsplit(self.base_url)
            if parts.scheme not in ("http", "https"):
                raise ValueError(f"base_url must be an http(s) URL, got {self.base_url!r}")
            if not parts.hostname:
                raise ValueError(f"base_url names no host: {self.base_url!r}")
            if parts.username or parts.password:
                # run.json records this URL's host, and no credential belongs in configuration.
                raise ValueError(
                    "base_url must not carry credentials; put the key in the environment "
                    "variable named by api_key_env"
                )
            # On the text: a bare `?` leaves `parts.query` empty and still breaks the appended path.
            if "?" in self.base_url or "#" in self.base_url:
                raise ValueError(
                    "base_url must not carry a query string or fragment, which the appended "
                    "path would land inside; put the key in the environment variable named "
                    "by api_key_env"
                )
            if parts.scheme == "http" and not (
                self.allow_insecure_http or _loopback(parts.hostname)
            ):
                raise ValueError(
                    f"base_url is plain http to {parts.hostname}, which sends the key and your "
                    f"source in the clear; use https, or set allow_insecure_http: true for a "
                    f"network you trust"
                )
        if self.provider != "none":
            missing = [
                name
                for name, value in (("base_url", self.base_url), ("model", self.model))
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"provider {self.provider!r} needs {' and '.join(missing)} to be set"
                )
        return self

    @property
    def host(self) -> str | None:
        """The host `run.json` records, never the whole URL."""
        return urlsplit(self.base_url).hostname if self.base_url is not None else None


class Config(_Frozen):
    """`.obelize.yml`, and the defaults that stand in for it when it is absent.

    Only the shape, so the evidence writer needs no YAML parser; `obelize.config` loads it and
    merges flags. docs/CLI.md lists every field and default (tests/unit/test_config.py checks).
    """

    include: StrictStr = DEFAULT_INCLUDE
    exclude: tuple[StrictStr, ...] = ()
    verify: VerifyConfig = Field(default_factory=VerifyConfig)
    allow_dirty: StrictBool = False
    max_file_bytes: StrictInt = Field(default=2_000_000, gt=0)

    @model_validator(mode="after")
    def _check(self) -> Config:
        for field, patterns in (("include", (self.include,)), ("exclude", self.exclude)):
            for pattern in patterns:
                if not pattern.strip():
                    raise ValueError(f"{field} takes a gitignore-style glob, got {pattern!r}")
                if "\\" in pattern:
                    raise ValueError(
                        f"{field} patterns use forward slashes on every platform, got {pattern!r}"
                    )
        if self.include.startswith("!"):
            raise ValueError("include cannot hold a negated pattern; put it in exclude")
        return self


__all__ = [
    "TIMEOUT_S",
    "Config",
    "ModelConfig",
    "VerifyConfig",
]
