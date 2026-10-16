"""The string types and validators the models share, and the frozen base they inherit."""

from __future__ import annotations

import keyword
import re
import shlex
import unicodedata
from collections.abc import Sequence
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, StrictStr

from obelize.models.vocabulary import ATOMICITY_BAIL, BailCode
from obelize.native import processes, shell

# PACK_SPEC.md hard rule 3; public because `obelize.packs.schema` checks it per field.
QUALIFIED_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
# A PEP 503 project name; hyphenated, so never a source-level symbol.
_DISTRIBUTION_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PLAIN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Commands run via `shlex` with `shell=False`, so `|` would silently be an argument.
_SHELL_OPERATORS = frozenset({"|", "||", "&", "&&", ";", ">", ">>", "<", "<<", "2>", "2>&1"})

# Unicode categories a terminal acts on; `_display_text` says why these three.
_REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})

# In characters: fits PACK_SPEC.md's longest limitation sentence and keeps a report row one row.
DISPLAY_TEXT_LIMIT = 500


def _relative_posix_path(value: str) -> str:
    """A repository-relative path with forward slashes, on every platform.

    No absolute path or `..` escape may reach evidence, a report or `--json` (TM-1).
    """
    if not value:
        raise ValueError("path must not be empty")
    if "\\" in value:
        raise ValueError(f"path must use forward slashes on every platform: {value!r}")
    if value.startswith("/"):
        raise ValueError(f"path must be relative to the scanned root: {value!r}")
    if ".." in value.split("/"):
        raise ValueError(f"path must not climb out of the scanned root: {value!r}")
    return value


def _sha256(value: str) -> str:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"expected a lower-case hex sha256 digest: {value!r}")
    return value


def _ascii_token(value: str) -> str:
    """ASCII only: prefilter tokens match raw bytes, where non-ASCII differs per encoding."""
    if not value:
        raise ValueError("a prefilter token must not be empty")
    if not value.isascii():
        raise ValueError(
            f"a prefilter token is matched against raw bytes, so it must be ASCII: {value!r}"
        )
    return value


def _runnable_command(value: str) -> str:
    """Refuse commands that cannot do what they look like; whether one may run is decided
    elsewhere, by the trust ladder.

    Unsplittable by `shlex`, holding shell operators, or rendering as another command in the
    terminal where a person approves it (tab and newline allowed).
    """
    try:
        tokens = shlex.split(value)
    except ValueError as error:
        raise ValueError(f"{value!r} does not split into arguments: {error}") from error
    if not tokens:
        raise ValueError("a verification command must not be empty")
    operators = [token for token in tokens if token in _SHELL_OPERATORS]
    if operators:
        raise ValueError(
            f"{value!r} runs without a shell, so {operators[0]!r} would be passed to "
            f"{tokens[0]!r} as an argument. Ask for a shell explicitly instead: {shell.SHELL}."
        )
    _terminal_safe(value, "a verification command", allowed="\t\n")
    return value


def _configured_command(value: str) -> str:
    """A command this system reads as written; a recorded one is not asked, so it loads anywhere."""
    problem = processes.command_problem(value)
    if problem is not None:
        raise ValueError(problem)
    return value


def schema_hint(**keywords: JsonValue) -> Any:
    """The part of a validator's rule that JSON Schema can state, which pydantic cannot derive from
    an `AfterValidator`; built from the validator's own constants so the two cannot diverge."""
    return Field(json_schema_extra=keywords)


RelativePath = Annotated[str, AfterValidator(_relative_posix_path), schema_hint(minLength=1)]
Sha256 = Annotated[str, AfterValidator(_sha256), schema_hint(pattern=_SHA256.pattern)]
PrefilterToken = Annotated[str, AfterValidator(_ascii_token), schema_hint(minLength=1)]
RunnableCommand = Annotated[StrictStr, AfterValidator(_runnable_command)]
ConfiguredCommand = Annotated[RunnableCommand, AfterValidator(_configured_command)]


def _qualified_name(value: str) -> str:
    """PACK_SPEC hard rule 3 per field, so the error names the YAML path of the bad key (rule 4)."""
    if not QUALIFIED_NAME.fullmatch(value):
        raise ValueError(f"expected a fully qualified symbol, got {value!r}")
    return value


def _distribution_name(value: str) -> str:
    if not _DISTRIBUTION_NAME.fullmatch(value):
        raise ValueError(f"expected a distribution name, got {value!r}")
    return value


def _plain_name(value: str) -> str:
    if not _PLAIN_NAME.fullmatch(value) or keyword.iskeyword(value):
        raise ValueError(
            f"expected a single Python identifier that is not a keyword, got {value!r}"
        )
    return value


def _display_text(value: str) -> str:
    """Untrusted pack text a terminal renders verbatim: message, suggestion, limitations, citation.

    Refuses Cc, Cf and Cs (ESC, carriage return or U+202E can make a command read as another) where
    the pack is read. `Co` and `Cn` only render as a glyph; refusing them pins a Unicode version.
    """
    if not value.strip():
        raise ValueError("display text must not be empty")
    if len(value) > DISPLAY_TEXT_LIMIT:
        raise ValueError(
            f"display text must be at most {DISPLAY_TEXT_LIMIT} characters, got {len(value)}"
        )
    _terminal_safe(value, "display text")
    if "\u2028" in value or "\u2029" in value:
        raise ValueError("display text must be one line, with no line or paragraph separator")
    return value


def terminal_unsafe(value: str, allowed: str = "") -> str | None:
    """Describe the first character not in `allowed` that a terminal would act on, else None."""
    for character in value:
        if character not in allowed and unicodedata.category(character) in _REFUSED_CATEGORIES:
            return f"U+{ord(character):04X} is {unicodedata.category(character)}"
    return None


def printable(value: str, allowed: str = "") -> str:
    """`value` with every character `terminal_unsafe` names spelled out, as `\\x1b` or `\\u202e`."""
    return "".join(
        character
        if terminal_unsafe(character, allowed) is None
        else character.encode("unicode_escape").decode("ascii")
        for character in value
    )


def _terminal_safe(value: str, what: str, allowed: str = "") -> None:
    unsafe = terminal_unsafe(value, allowed)
    if unsafe is not None:
        raise ValueError(
            f"{what} must not carry a control, format or surrogate character; {unsafe} in {value!r}"
        )


QualifiedName = Annotated[
    str, AfterValidator(_qualified_name), schema_hint(pattern=QUALIFIED_NAME.pattern)
]
DistributionName = Annotated[
    str, AfterValidator(_distribution_name), schema_hint(pattern=_DISTRIBUTION_NAME.pattern)
]
PlainName = Annotated[str, AfterValidator(_plain_name), schema_hint(pattern=_PLAIN_NAME.pattern)]
DisplayText = Annotated[
    str, AfterValidator(_display_text), schema_hint(minLength=1, maxLength=DISPLAY_TEXT_LIMIT)
]


def sorted_unique(values: Sequence[Any], field: str) -> None:
    """An unordered field has exactly one spelling."""
    if list(values) != sorted(set(values)):
        raise ValueError(f"{field} must be sorted and de-duplicated, got {list(values)}")


def _check_caused_by(bail: str | None, caused_by: tuple[BailCode, ...] | None, field: str) -> None:
    """`caused_by` exactly on the atomicity bail: the whole cause set, sorted."""
    if bail != ATOMICITY_BAIL:
        if caused_by is not None:
            raise ValueError(
                f"{field}={bail!r} names its own defect, so it must not carry caused_by"
            )
        return
    if not caused_by:
        raise ValueError(
            f"{field}={ATOMICITY_BAIL!r} names no defect, so it must name the ones that do"
        )
    if ATOMICITY_BAIL in caused_by:
        raise ValueError(f"caused_by must not name {ATOMICITY_BAIL!r} itself")
    sorted_unique(caused_by, "caused_by")


class _Frozen(BaseModel):
    """Immutable and closed: an unknown key is a bug.

    `json_schema_serialization_defaults_required`: writers dump defaults too, so the published
    schema marks every field required.
    """

    model_config = ConfigDict(
        frozen=True, extra="forbid", json_schema_serialization_defaults_required=True
    )


__all__ = [
    "DISPLAY_TEXT_LIMIT",
    "QUALIFIED_NAME",
    "ConfiguredCommand",
    "DisplayText",
    "DistributionName",
    "PlainName",
    "PrefilterToken",
    "QualifiedName",
    "RelativePath",
    "RunnableCommand",
    "Sha256",
    "printable",
    "schema_hint",
    "sorted_unique",
    "terminal_unsafe",
]
