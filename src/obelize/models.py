"""Shared pydantic models and the closed vocabularies every other module reads.

Vocabularies are `Literal`s (wire strings, unlike an Enum) with a `get_args` frozenset each;
tests/unit/test_models.py checks them against docs/SCAN_VOCABULARY.md. Models refuse, never
repair: one that sorted its input would hide a determinism bug. No libcst, typer or pyyaml, and
`obelize.cli` must print `--help` without pydantic.
"""

from __future__ import annotations

import re
import shlex
import unicodedata
from collections.abc import Sequence
from typing import Annotated, Any, Literal, get_args
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from obelize.native import processes

FindingKind = Literal[
    "import",
    "call",
    "attribute",
    "method_call",
    "dynamic",
    "star_import",
    "text_mention",
    "manifest",
    "parse_error",
]
FINDING_KINDS: frozenset[FindingKind] = frozenset(get_args(FindingKind))

ConfidenceReason = Literal[
    "direct_import_resolved",
    "alias_resolved",
    "from_import_resolved",
    "conditional_binding",
    "module_alias_rebound",
    "receiver_bound_same_scope",
    "receiver_bound_module_const",
    "receiver_bound_self_attr",
    "receiver_unresolved",
    "dynamic_access",
    "star_import",
    "star_import_candidate",
    "string_or_comment_mention",
    "mock_patch_target",
    "manifest_dependency",
    "parse_error",
]
CONFIDENCE_REASONS: frozenset[ConfidenceReason] = frozenset(get_args(ConfidenceReason))

Verdict = Literal["auto", "needs_review", "unsupported", "not_a_usage"]
VERDICTS: frozenset[Verdict] = frozenset(get_args(Verdict))

BailCode = Literal[
    # Scanner and file handling
    "roundtrip_mismatch",
    "input_does_not_parse",
    "output_does_not_parse",
    "output_names_unresolved",
    "file_too_large",
    "runtime_unsupported",
    # Resolution and bindings
    "conditional_binding",
    "module_alias_rebound",
    "model_object_escapes",
    "model_object_read_elsewhere",
    "multiple_assignments",
    "class_attr_binding",
    "receiver_unresolved",
    "receiver_method_unmapped",
    # Client
    "multiple_configure_calls",
    "client_source_unresolved",
    "client_name_collision",
    "client_placement_ambiguous",
    "configure_kwargs_unsupported",
    "credentials_shape_differs",
    # Imports and manifests
    "alias_collision",
    "type_symbol_unmapped",
    "from_import_unmigrated_symbol",
    "local_import",
    "star_import",
    "file_not_fully_migrated",
    "repo_not_fully_migrated",
    "transitive_dependency_in_use",
    "manifest_code_mismatch",
    "manifest_pin_shape_unsupported",
    # Call rewrites
    "unknown_ctor_kwarg",
    "positional_arg_ambiguous",
    "default_model_name_required",
    "generation_config_not_static",
    "safety_settings_not_static",
    "history_parts_shape_incompatible",
    "dynamic_stream_flag",
    "async_stream_await_missing",
    "unsupported_kwarg",
    "afc_semantics_differ",
    "response_shape_changed",
    "count_tokens_config_carries_semantics",
    "ctor_argument_not_portable",
    "attribute_removed",
    "flag_only_surface",
    "file_object_fields_not_verified",
    "types_import_typing_only",
    "error_class_changed",
    # The run
    "usage_unmapped",
    "configure_consumed_elsewhere",
]
BAIL_CODES: frozenset[BailCode] = frozenset(get_args(BailCode))

WarningCode = Literal[
    "client_constructed_eagerly",
    "model_name_looks_prefixed",
    "count_tokens_config_dropped",
    "tests_touched_by_migration",
    "positional_args_mapped_by_index",
    "history_parts_rewritten",
    "async_stream_await_preserved",
    "stale_mock_target",
]
WARNING_CODES: frozenset[WarningCode] = frozenset(get_args(WarningCode))

# An import finding is the statement itself, so only a bail about the statement, the
# whole file or atomicity may withhold it; a downstream group's bail would double-count its defect.
IMPORT_BAILS: frozenset[BailCode] = frozenset(
    {
        "roundtrip_mismatch",
        "output_does_not_parse",
        "output_names_unresolved",
        "flag_only_surface",
        "module_alias_rebound",
        "conditional_binding",
        "star_import",
        "local_import",
        "alias_collision",
        "type_symbol_unmapped",
        "from_import_unmigrated_symbol",
        "file_not_fully_migrated",
        "usage_unmapped",
    }
)

IMPORT_KINDS: frozenset[FindingKind] = frozenset({"import", "star_import"})

# Names no defect of its own, so it carries `caused_by` naming the ones that do.
ATOMICITY_BAIL: BailCode = "file_not_fully_migrated"

# Atomicity for the repository: carries no `caused_by`, since its cause is files, not codes.
REPO_ATOMICITY_BAIL: BailCode = "repo_not_fully_migrated"

EditStatus = Literal["auto", "needs_review", "unsupported", "model_proposed"]
EDIT_STATUSES: frozenset[EditStatus] = frozenset(get_args(EditStatus))

BindingKind = Literal["name", "module_const", "self_attr", "class_attr"]
BINDING_KINDS: frozenset[BindingKind] = frozenset(get_args(BindingKind))

ScanStatus = Literal["eligible", "needs_review", "unsupported", "not_a_usage"]
SCAN_STATUSES: frozenset[ScanStatus] = frozenset(get_args(ScanStatus))

# Statuses that withhold the edit and must name a bail, for ScanStatus and EditStatus alike.
# `model_proposed` is not one, yet keeps the bail the rules refused with.
WITHHELD: frozenset[str] = frozenset({"needs_review", "unsupported"})

# Why the walker skipped a path; closed so dropped files never look like an empty repository.
SkipReason = Literal[
    "missing",
    "not_a_file",
    "outside_root",
    "submodule",
    "symlink",
    "unreadable",
    "unusable_name",
]
SKIP_REASONS: frozenset[SkipReason] = frozenset(get_args(SkipReason))

# The SkipReasons `obelize.fsutil.refusal` decides from one path alone; `fsutil.WriteRefusal`
# is these plus one.
PathRefusal = Literal["missing", "not_a_file", "outside_root", "symlink", "unreadable"]
PATH_REFUSALS: frozenset[PathRefusal] = frozenset(get_args(PathRefusal))

# `flag_only.patterns`: closed ids, not regexes, since a pack may not carry behaviour.
FlagOnlyPattern = Literal["mock_patch_target", "dynamic_access", "sys_modules_stub"]
FLAG_ONLY_PATTERNS: frozenset[FlagOnlyPattern] = frozenset(get_args(FlagOnlyPattern))

# `atomic` withholds a file's import rewrite if anything else in it bails; `dual` keeps both
# imports and rewrites only what resolved.
ImportPolicy = Literal["atomic", "dual"]
IMPORT_POLICIES: frozenset[ImportPolicy] = frozenset(get_args(ImportPolicy))
DEFAULT_IMPORT_POLICY: ImportPolicy = "atomic"

# `model.provider`; the default `none` is a promise that no endpoint is contacted. Not the adapter
# protocol, which is `obelize.providers.base.ModelProvider`.
ProviderName = Literal["none", "openai_compat"]
PROVIDER_NAMES: frozenset[ProviderName] = frozenset(get_args(ProviderName))

# Why a withheld row was not put to a model, in `providers.base.consult`'s order. This set and
# the next three are defined member by member in docs/RUN_FOLDER.md.
ConsultSkip = Literal[
    "atomicity_only",
    "consumed_elsewhere",
    "context_too_large",
    "not_a_source_file",
    "not_needs_review",
    "pack_refused",
]
CONSULT_SKIPS: frozenset[ConsultSkip] = frozenset(get_args(ConsultSkip))

# Why `obelize.providers.guard` refused a proposal; the first refusal in its order is recorded.
# `file_changed_since_read` is RefusalCode's word on purpose; parse and compile both stay because
# `await` outside `async` passes libcst and fails `compile()`.
GuardRefusal = Literal[
    "file_changed_since_read",
    "import_outside_the_target",
    "name_outside_the_question",
    "output_does_not_compile",
    "output_does_not_parse",
    "outside_the_context",
    "path_not_python",
    "path_not_the_consulted_file",
    "path_outside_root",
    "replacement_not_displayable",
    "replacement_not_encodable",
    "replacement_runs_past_its_range",
    "replacement_too_large",
    "site_not_replaced",
    "symbol_mismatch",
]
GUARD_REFUSALS: frozenset[GuardRefusal] = frozenset(get_args(GuardRefusal))

# Why an adapter could not answer: stages of one pipeline in the order the bytes reach them, so
# unlike GuardRefusal the order is not a choice. A 3xx is refused, never followed: the payload
# and `Authorization` header must not reach a host the run never printed.
ProviderFailure = Literal[
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
PROVIDER_FAILURES: frozenset[ProviderFailure] = frozenset(get_args(ProviderFailure))

# What became of one consultation, first match in `obelize.providers.proposals`' order: answer
# before run, permission before placement.
ProposalOutcome = Literal[
    "file_already_proposed",
    "guard_refused",
    "not_accepted",
    "not_applied",
    "nothing_proposed",
    "unanswered",
    "write_refused",
    "written",
]
PROPOSAL_OUTCOMES: frozenset[ProposalOutcome] = frozenset(get_args(ProposalOutcome))

# Outcomes where a proposal came back and nothing was wrong with it.
PROPOSAL_HELD: frozenset[ProposalOutcome] = frozenset(
    {"file_already_proposed", "not_accepted", "not_applied", "write_refused", "written"}
)

# docs/CLI.md documents this exact string; tests/unit/test_config.py reads it back.
DEFAULT_INCLUDE = "**/*.py"

# Verification vocabularies, published in docs/CLI.md (not SCAN_VOCABULARY.md) and checked
# both ways by tests/unit/test_verify_vocabulary.py.

# `inconclusive`: a command was asked and did not answer; `not_run`: none was asked.
VerifyStatus = Literal["pass", "fail", "inconclusive", "not_run"]
VERIFY_STATUSES: frozenset[VerifyStatus] = frozenset(get_args(VerifyStatus))

# Worst first; a run takes the worst of its commands. A verdict beats none, and a
# phase where some command never ran has not passed.
VERIFY_STATUS_ORDER: tuple[VerifyStatus, ...] = ("fail", "inconclusive", "not_run", "pass")

# `command_not_executable` is not `command_failed`: exit 3 would blame the migration for a
# program missing from PATH.
VerifyReason = Literal[
    "baseline_failed",
    "changed_file_does_not_compile",
    "command_failed",
    "command_not_executable",
    "dry_run",
    "no_changes_to_verify",
    "no_verify_commands",
    "policy_refused",
    "timeout",
    "tree_changed",
]
VERIFY_REASONS: frozenset[VerifyReason] = frozenset(get_args(VerifyReason))

# docs/CLI.md's status/reason table; a `pass` needs no explaining, so it takes none.
REASONS_BY_STATUS: dict[VerifyStatus, frozenset[VerifyReason]] = {
    "pass": frozenset(),
    "fail": frozenset({"changed_file_does_not_compile", "command_failed"}),
    "inconclusive": frozenset(
        {"baseline_failed", "command_not_executable", "timeout", "tree_changed"}
    ),
    "not_run": frozenset(
        {"dry_run", "no_changes_to_verify", "no_verify_commands", "policy_refused"}
    ),
}

# The reasons one command can produce alone; every other reason is about the run.
COMMAND_REASONS: frozenset[VerifyReason] = frozenset(
    {"command_failed", "command_not_executable", "timeout"}
)

# `not_run` reasons that owed no verdict; any other `not_run` is a missing one.
NO_VERDICT_EXPECTED: frozenset[VerifyReason] = frozenset({"dry_run", "no_changes_to_verify"})

# The trust rung a command ran under: why it was allowed, not where it was read. A
# pack's `verification.suggestions` are only displayed, so never appear.
CommandSource = Literal["cli", "user_allowlist", "repo_config"]
COMMAND_SOURCES: frozenset[CommandSource] = frozenset(get_args(CommandSource))

# PACK_SPEC.md hard rule 3; public because `obelize.packs.schema` checks it per field.
QUALIFIED_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
# A PEP 503 project name; hyphenated, so never a source-level symbol.
_DISTRIBUTION_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PLAIN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# The user config names the variable holding the API key, never the key; a pasted `sk-...` key
# fails because `-` is not a name character.
_ENV_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

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
            f"{tokens[0]!r} as an argument. Ask for a shell explicitly instead: "
            f"sh -c '<command>'."
        )
    _terminal_safe(value, "a verification command", allowed="\t\n")
    return value


def _configured_command(value: str) -> str:
    """A command this system reads as written; a recorded one is not asked, so it loads anywhere."""
    problem = processes.command_problem(value)
    if problem is not None:
        raise ValueError(problem)
    return value


RelativePath = Annotated[str, AfterValidator(_relative_posix_path)]
Sha256 = Annotated[str, AfterValidator(_sha256)]
PrefilterToken = Annotated[str, AfterValidator(_ascii_token)]
RunnableCommand = Annotated[str, AfterValidator(_runnable_command)]
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
    if not _PLAIN_NAME.fullmatch(value):
        raise ValueError(f"expected a single Python identifier, got {value!r}")
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
    return value


def terminal_unsafe(value: str, allowed: str = "") -> str | None:
    """Describe the first character not in `allowed` that a terminal would act on, else None."""
    for character in value:
        if character not in allowed and unicodedata.category(character) in _REFUSED_CATEGORIES:
            return f"U+{ord(character):04X} is {unicodedata.category(character)}"
    return None


def _terminal_safe(value: str, what: str, allowed: str = "") -> None:
    unsafe = terminal_unsafe(value, allowed)
    if unsafe is not None:
        raise ValueError(
            f"{what} must not carry a control, format or surrogate character; {unsafe} in {value!r}"
        )


QualifiedName = Annotated[str, AfterValidator(_qualified_name)]
DistributionName = Annotated[str, AfterValidator(_distribution_name)]
PlainName = Annotated[str, AfterValidator(_plain_name)]
DisplayText = Annotated[str, AfterValidator(_display_text)]


def _sorted_unique(values: Sequence[Any], field: str) -> None:
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
    _sorted_unique(caused_by, "caused_by")


def _identifier(value: str, segments: int | None = None) -> bool:
    """Whether `value` is a dotted name Python accepts, in `segments` parts if given.

    Unicode on purpose (PEP 3131): source may say `modèle`. Pack names use `QUALIFIED_NAME`.
    """
    parts = value.split(".")
    counted = segments is None or len(parts) == segments
    return counted and all(part.isidentifier() for part in parts)


def _check_withheld(status: str, reason: str | None, field: str) -> None:
    """Withheld iff a reason is named, both ways; `model_proposed` may keep one anyway."""
    if status in WITHHELD:
        if reason is None:
            raise ValueError(f"status={status!r} withholds the edit, so it must name a bail code")
    elif reason is not None and status != "model_proposed":
        raise ValueError(
            f"status={status!r} is not withheld, so it must not carry {field}={reason!r}"
        )


class _Frozen(BaseModel):
    """Immutable and closed: an unknown key is a bug.

    `json_schema_serialization_defaults_required`: writers dump defaults too, so the published
    schema marks every field required.
    """

    model_config = ConfigDict(
        frozen=True, extra="forbid", json_schema_serialization_defaults_required=True
    )


class Finding(_Frozen):
    """One legacy usage the scanner resolved, or one file it could not read."""

    path: RelativePath
    line: int = Field(ge=1)
    column: int = Field(ge=0)
    kind: FindingKind
    confidence_reason: ConfidenceReason
    symbol: str | None = None
    evidence: str | None = None
    # Scan-time only, no verdict or warning yet: `eligible` is necessary for `auto`, not enough.
    scan_status: ScanStatus
    bail: BailCode | None = None
    caused_by: tuple[BailCode, ...] | None = None

    @property
    def sort_key(self) -> tuple[str, int, int, str, str]:
        """Document order, defined once; libcst's reference sets vary per process, so sort by it."""
        return (self.path, self.line, self.column, self.kind, self.symbol or "")

    @model_validator(mode="after")
    def _check(self) -> Finding:
        _check_withheld(self.scan_status, self.bail, "bail")
        _check_caused_by(self.bail, self.caused_by, "bail")

        if self.kind in IMPORT_KINDS and self.bail is not None and self.bail not in IMPORT_BAILS:
            raise ValueError(
                f"{self.path}:{self.line} is an import finding carrying bail {self.bail!r}, which "
                f"an import may not carry. If the import itself resolved, the code is "
                f"{ATOMICITY_BAIL!r} with caused_by=[{self.bail!r}]"
            )

        # An unparsable file yields exactly one finding, so kind and reason coincide.
        if (self.kind == "parse_error") != (self.confidence_reason == "parse_error"):
            raise ValueError("kind and confidence_reason `parse_error` are one fact; use both")
        if self.kind == "star_import" and self.confidence_reason != "star_import":
            raise ValueError("a star import statement resolves as `star_import`")
        if (self.kind == "manifest") != (self.confidence_reason == "manifest_dependency"):
            raise ValueError(
                "`manifest_dependency` is the reason of a `manifest` finding, and only"
            )
        mention = self.confidence_reason in {"string_or_comment_mention", "mock_patch_target"}
        if (self.kind == "text_mention") != mention:
            raise ValueError("a `text_mention` is resolved from a string, and a string only")
        if self.scan_status == "not_a_usage" and self.kind not in {"text_mention", "manifest"}:
            raise ValueError(
                f"`not_a_usage` is for something that is not an edit (a prose mention, or a "
                f"manifest line that disagrees with the code), not for kind {self.kind!r}"
            )
        self._check_symbol()
        return self

    def _check_symbol(self) -> None:
        if self.kind == "parse_error":
            # No source excerpt in evidence: only the fixture ground truth names a line.
            if self.symbol is not None:
                raise ValueError(
                    "a parse_error finding names no symbol; it is not a resolved usage"
                )
            return
        if self.symbol is None:
            raise ValueError(f"a {self.kind!r} finding must name the symbol it resolved")
        named = (
            _DISTRIBUTION_NAME.fullmatch(self.symbol) is not None
            if self.kind == "manifest"
            else _identifier(self.symbol)
        )
        if not named:
            raise ValueError(
                f"symbol {self.symbol!r} is not a "
                f"{'distribution name' if self.kind == 'manifest' else 'qualified name'}. A quoted "
                f"mock target is recorded unquoted, and a source excerpt is never a symbol"
            )


class Binding(_Frozen):
    """A name bound to a legacy object, and every place it is used.

    Kinds are a closed table. A group is atomic: if one reference escapes, all are
    withheld, because a half-rewritten group breaks working code.
    """

    kind: BindingKind
    name: str
    scope: str
    path: RelativePath | None = None
    ctor_line: int = Field(ge=1)
    use_lines: tuple[int, ...] = ()
    scan_status: ScanStatus
    bail: BailCode | None = None

    @model_validator(mode="after")
    def _check(self) -> Binding:
        _check_withheld(self.scan_status, self.bail, "bail")
        if self.bail == ATOMICITY_BAIL:
            # Atomicity belongs to a file, and not every fixture gives a binding row a path.
            raise ValueError(f"a binding never carries {ATOMICITY_BAIL!r}")
        kind, _, owner = self.scope.partition(":")
        if self.scope != "module" and not (kind in {"function", "class"} and _identifier(owner, 1)):
            raise ValueError(
                f"scope is `module`, `function:<name>` or `class:<name>`: {self.scope!r}"
            )
        expected = {
            "name": "function:",
            "module_const": "module",
            "self_attr": "class:",
            "class_attr": "class:",
        }[self.kind]
        if not self.scope.startswith(expected):
            raise ValueError(
                f"a {self.kind!r} binding lives in {expected!r}, not in {self.scope!r}"
            )
        segments = 2 if self.kind == "self_attr" else 1
        if not _identifier(self.name, segments):
            raise ValueError(
                f"a {self.kind!r} binding is named by {segments} identifier(s), got {self.name!r}"
            )
        if list(self.use_lines) != sorted(set(self.use_lines)):
            raise ValueError(
                f"use_lines must be sorted and de-duplicated, got {list(self.use_lines)}"
            )
        if any(line < 1 for line in self.use_lines):
            raise ValueError(f"use_lines are 1-based, got {list(self.use_lines)}")
        return self


class Edit(_Frozen):
    """What a rule did with a finding, or why it refused to."""

    path: RelativePath
    line: int = Field(ge=1)
    # Deliberately not the fixture `verdict`: `not_a_usage` is never an edit, and
    # `model_proposed` cannot be graded by a hand-written answer key.
    status: EditStatus
    rule_id: str | None = None
    reason: BailCode | None = None
    caused_by: tuple[BailCode, ...] | None = None
    warnings: tuple[WarningCode, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> Edit:
        _check_withheld(self.status, self.reason, "reason")
        _check_caused_by(self.reason, self.caused_by, "reason")
        if self.status == "auto" and self.rule_id is None:
            # Every applied hunk must trace to a pack rule via run.json's `file_edits[].rules`.
            raise ValueError("an applied edit must name the pack rule that produced it")
        if self.status == "model_proposed":
            if self.rule_id is not None:
                raise ValueError(
                    "a model proposal is not produced by a pack rule; rule_id stays unset"
                )
            if self.reason is None:
                raise ValueError(
                    "a model proposal exists only where the deterministic rules refused, and the "
                    "report has to say what they refused"
                )
        _sorted_unique(self.warnings, "warnings")
        return self


class EditProposal(_Frozen):
    """A model's proposed edit, held exactly as it came back."""

    # Plain `str` fields on purpose: a hostile path must be constructible so the
    # guard can refuse it by name. Failing even these checks makes it unanswered, not refused.
    path: str
    # 1-based, inclusive; the guard checks it against the range sent as context.
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    # The legacy symbol it claims to migrate; the guard checks it is at that line.
    symbol: str
    # The range's new text: newline-separated, no trailing newline.
    replacement: str
    # For the report; it never reaches the tree.
    rationale: str

    @model_validator(mode="after")
    def _check(self) -> EditProposal:
        if self.end_line < self.start_line:
            raise ValueError(
                f"a proposal replaces lines {self.start_line}..{self.end_line}, which is "
                f"no range at all"
            )
        for field, value in (
            ("path", self.path),
            ("symbol", self.symbol),
            ("rationale", self.rationale),
        ):
            if not value.strip():
                raise ValueError(f"{field} is empty, so the proposal names nothing")
        return self


class ReceiverMethods(_Frozen):
    """The methods a legacy receiver supports, by the symbol that constructs it."""

    receiver: str
    methods: tuple[str, ...]

    @model_validator(mode="after")
    def _check(self) -> ReceiverMethods:
        if not QUALIFIED_NAME.fullmatch(self.receiver):
            raise ValueError(f"receiver must be a qualified name, got {self.receiver!r}")
        if not self.methods:
            raise ValueError(f"{self.receiver} supports no methods; drop the entry instead")
        _sorted_unique(self.methods, "methods")
        return self


class MethodReturn(_Frozen):
    """A supported method, and the legacy receiver its result is.

    Without it `chat.send_message(...)` resolves to nothing: `ChatSession` has no constructor,
    only `GenerativeModel.start_chat(...)`.
    """

    method: str
    receiver: str

    @model_validator(mode="after")
    def _check(self) -> MethodReturn:
        for field, value in (("method", self.method), ("receiver", self.receiver)):
            if not QUALIFIED_NAME.fullmatch(value):
                raise ValueError(f"{field} must be a qualified name, got {value!r}")
        if self.method.rpartition(".")[0] == self.receiver:
            raise ValueError(
                f"{self.method} would produce the receiver it is called on; a method that "
                f"returns its own receiver needs no entry"
            )
        return self


class ProvidedModule(_Frozen):
    """A module the legacy distribution installed and the new one does not.

    Importing one relies on an undeclared dependency that leaves with the legacy pin.
    """

    module: str
    distribution: str

    @model_validator(mode="after")
    def _check(self) -> ProvidedModule:
        if not QUALIFIED_NAME.fullmatch(self.module):
            raise ValueError(f"module must be a dotted name, got {self.module!r}")
        return self


class ScanSpec(_Frozen):
    """Everything the scanner needs from a pack, and nothing it must not have.

    `scan/*` and `impact/*` never import `packs.schema`; `packs/loader.py` builds this with
    `to_scan_spec()`, keeping rewrite data out of the scanner.
    """

    pack_id: str
    pack_version: str
    pack_sha256: Sha256
    legacy_modules: tuple[str, ...]
    legacy_distribution: str
    new_distribution: str
    prefilter_tokens: tuple[PrefilterToken, ...]
    symbols: tuple[str, ...] = ()
    client_symbol: str
    constructor_symbols: tuple[str, ...] = ()
    supported_methods: tuple[ReceiverMethods, ...] = ()
    method_returns: tuple[MethodReturn, ...] = ()
    removed_attributes: tuple[str, ...] = ()
    flag_only_symbols: tuple[str, ...] = ()
    flag_only_patterns: tuple[FlagOnlyPattern, ...] = ()
    # Modules that came with the legacy pin, which the manifest pin check inspects before the
    # pin may go.
    transitive_modules: tuple[ProvidedModule, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> ScanSpec:
        if not self.legacy_modules:
            raise ValueError("legacy_modules must name at least one module")
        if not self.prefilter_tokens:
            raise ValueError("without a prefilter token every file in the repository is parsed")
        for field, values in (
            ("legacy_modules", self.legacy_modules),
            ("symbols", self.symbols),
            ("constructor_symbols", self.constructor_symbols),
            ("removed_attributes", self.removed_attributes),
            ("flag_only_symbols", self.flag_only_symbols),
        ):
            _sorted_unique(values, field)
            bad = [value for value in values if not QUALIFIED_NAME.fullmatch(value)]
            if bad:
                raise ValueError(f"{field} takes qualified names, got {bad}")
        _sorted_unique(self.prefilter_tokens, "prefilter_tokens")
        _sorted_unique(self.flag_only_patterns, "flag_only_patterns")
        for field, value in (
            ("legacy_distribution", self.legacy_distribution),
            ("new_distribution", self.new_distribution),
        ):
            if not _DISTRIBUTION_NAME.fullmatch(value):
                raise ValueError(f"{field} takes a distribution name, got {value!r}")
        if not QUALIFIED_NAME.fullmatch(self.client_symbol):
            raise ValueError(f"client_symbol must be a qualified name, got {self.client_symbol!r}")
        receivers = tuple(entry.receiver for entry in self.supported_methods)
        _sorted_unique(receivers, "supported_methods")
        _sorted_unique(tuple(entry.method for entry in self.method_returns), "method_returns")
        for entry in self.method_returns:
            owner, _, method = entry.method.rpartition(".")
            if method not in self.methods_for(owner):
                raise ValueError(
                    f"method_returns names {entry.method}, which is not a supported method of "
                    f"{owner or '(nothing)'}"
                )
            if entry.receiver not in receivers:
                raise ValueError(
                    f"{entry.method} is said to produce {entry.receiver}, which supports no "
                    f"methods; a receiver the scanner can hold and do nothing with is not one"
                )
        produced = {entry.receiver for entry in self.method_returns}
        unreachable = sorted(set(receivers) - set(self.constructor_symbols) - produced)
        if unreachable:
            raise ValueError(
                f"nothing in this spec can produce {unreachable}: a receiver is held by a "
                f"constructor call or by a method that returns it, and these are neither, so "
                f"their methods would never resolve"
            )
        return self

    def methods_for(self, receiver: str) -> tuple[str, ...]:
        """The supported methods of `receiver`, or `()` when it has none.

        The escape rule: a bound name used other than as their receiver withholds its group.
        """
        for entry in self.supported_methods:
            if entry.receiver == receiver:
                return entry.methods
        return ()


class ImpactPolicy(_Frozen):
    """Repository-wide switches the impact planner reads.

    Not in `ScanSpec`: a pack may not set them, and the cache key (pack and file hash)
    would miss them.
    """

    import_policy: ImportPolicy = DEFAULT_IMPORT_POLICY


class ImpactPlan(_Frozen):
    """One file's findings and binding groups, after every scan-time rule.

    Under `atomic`, a file with any withheld row is left exactly as it was, so no plan
    that edits half a file can be built; under `dual` nothing is withheld for atomicity.
    `manifest` findings are refused: the manifest pin check grades them repo-wide in
    `ManifestPlan`.
    """

    path: RelativePath
    findings: tuple[Finding, ...] = ()
    bindings: tuple[Binding, ...] = ()
    import_policy: ImportPolicy = DEFAULT_IMPORT_POLICY

    @model_validator(mode="after")
    def _check(self) -> ImpactPlan:
        elsewhere = sorted(
            {row.path for row in self.findings if row.path != self.path}
            | {str(row.path) for row in self.bindings if row.path != self.path}
        )
        if elsewhere:
            raise ValueError(
                f"a plan for {self.path!r} carries rows about {elsewhere}; a plan is one file's"
            )
        if any(finding.kind == "manifest" for finding in self.findings):
            raise ValueError(
                "a manifest is not a parsed source file; a `manifest` finding does not belong "
                "to a file's plan"
            )
        keys = [finding.sort_key for finding in self.findings]
        if keys != sorted(keys):
            raise ValueError("findings are written in document order; sort before emitting")
        rows = [(row.ctor_line, row.scope, row.name) for row in self.bindings]
        if rows != sorted(rows):
            raise ValueError("bindings are written in constructor order; sort before emitting")

        withheld = [row.line for row in self.findings if row.scan_status in WITHHELD]
        eligible = [row.line for row in self.findings if row.scan_status == "eligible"]
        if self.import_policy == "atomic" and withheld and eligible:
            raise ValueError(
                f"{self.path}: lines {eligible} are eligible while lines {withheld} are "
                f"withheld. A file with a withheld finding is left exactly as it was, so the "
                f"eligible rows carry {ATOMICITY_BAIL!r} with `caused_by` naming what withheld "
                f"the rest"
            )
        stamped = [row.line for row in self.findings if row.bail == ATOMICITY_BAIL]
        if self.import_policy == "dual" and stamped:
            raise ValueError(
                f"{self.path}: `dual` leaves both imports in place and rewrites what resolved, "
                f"so no finding is withheld for atomicity; lines {stamped} are"
            )
        return self


class ManifestPlan(_Frozen):
    """The repository's dependency declarations, after the manifest pin check's two edits.

    Repo-wide, and unlike `ImpactPlan` an applied edit may sit beside a withheld one: both pins
    keep a partial migration installable. `blocking` and `transitive` are the in-scope files
    behind `repo_not_fully_migrated` and `transitive_dependency_in_use`, required when either
    appears; `excluded` files do not block the removal but are named, since it breaks them too.
    """

    findings: tuple[Finding, ...] = ()
    blocking: tuple[RelativePath, ...] = ()
    excluded: tuple[RelativePath, ...] = ()
    transitive: tuple[RelativePath, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> ManifestPlan:
        kinds = sorted({row.kind for row in self.findings if row.kind != "manifest"})
        if kinds:
            raise ValueError(
                f"a manifest plan grades dependency declarations and nothing else, got {kinds}"
            )
        stamped = [row.line for row in self.findings if row.bail == ATOMICITY_BAIL]
        if stamped:
            raise ValueError(
                f"{ATOMICITY_BAIL!r} is a property of a parsed source file; lines {stamped} are "
                f"manifest declarations, whose atomicity is {REPO_ATOMICITY_BAIL!r}"
            )
        keys = [row.sort_key for row in self.findings]
        if keys != sorted(keys):
            raise ValueError("findings are written in document order; sort before emitting")
        _sorted_unique(self.blocking, "blocking")
        _sorted_unique(self.excluded, "excluded")
        _sorted_unique(self.transitive, "transitive")
        for code, named, claim in (
            (REPO_ATOMICITY_BAIL, self.blocking, "still imports the legacy distribution"),
            (
                "transitive_dependency_in_use",
                self.transitive,
                "imports a module only the legacy distribution installs",
            ),
        ):
            withheld = [row.line for row in self.findings if row.bail == code]
            if withheld and not named:
                raise ValueError(
                    f"lines {withheld} are withheld with {code!r}, which claims that an "
                    f"in-scope file {claim}, and none is named"
                )
        return self


class VerifyConfig(_Frozen):
    """`verify:` in `.obelize.yml`.

    Listing a command does not trust it: it is confirmed interactively and refused under
    `--non-interactive` or CI unless allowlisted or `--trust-repo-config` is passed.
    Deliberately neither sorted nor de-duplicated: the list is a script.
    """

    commands: tuple[ConfiguredCommand, ...] = ()
    timeout_s: int = Field(default=600, gt=0)
    junit: bool = True


class ModelConfig(_Frozen):
    """`model:` in the user's own `~/.config/obelize/config.yml`, and nowhere else.

    A repository's `.obelize.yml` may not set it: where code and a credential are
    sent is the runner's choice, not the migrated code's.
    """

    provider: ProviderName = "none"
    base_url: str | None = None
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
        """The host `run.json` records -- never the whole URL, which can carry a query."""
        return urlsplit(self.base_url).hostname if self.base_url is not None else None


class Config(_Frozen):
    """`.obelize.yml`, and the defaults that stand in for it when it is absent.

    Only the shape, so the evidence writer needs no YAML parser; `obelize.config` loads it and
    merges flags. docs/CLI.md lists every field and default (tests/unit/test_config.py checks).
    """

    include: str = DEFAULT_INCLUDE
    exclude: tuple[str, ...] = ()
    verify: VerifyConfig = Field(default_factory=VerifyConfig)
    allow_dirty: bool = False
    max_file_bytes: int = Field(default=2_000_000, gt=0)

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


class PackRef(_Frozen):
    """The pack a document was produced with, as `run.json` records it."""

    id: str
    version: str
    sha256: Sha256


class ScanCounts(_Frozen):
    """A summary of the findings, never a substitute for them."""

    files_selected: int = Field(ge=0)
    files_parsed: int = Field(ge=0)
    findings: int = Field(ge=0)
    eligible: int = Field(ge=0)
    needs_review: int = Field(ge=0)
    unsupported: int = Field(ge=0)
    not_a_usage: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> ScanCounts:
        if self.files_parsed > self.files_selected:
            raise ValueError("more files were parsed than were selected")
        split = self.eligible + self.needs_review + self.unsupported + self.not_a_usage
        if split != self.findings:
            raise ValueError(f"the status split sums to {split}, and there are {self.findings}")
        return self


class FindingsDocument(_Frozen):
    """The `findings.json` document, which `obelize scan --json` also prints."""

    # Nothing time-derived: two runs over the same input are byte-identical.

    obelize_version: str
    pack: PackRef
    counts: ScanCounts
    findings: tuple[Finding, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> FindingsDocument:
        keys = [finding.sort_key for finding in self.findings]
        if keys != sorted(keys):
            raise ValueError("findings are written in document order; sort before emitting")
        counted = dict.fromkeys(sorted(SCAN_STATUSES), 0)
        for finding in self.findings:
            counted[finding.scan_status] += 1
        recorded = {
            "eligible": self.counts.eligible,
            "needs_review": self.counts.needs_review,
            "not_a_usage": self.counts.not_a_usage,
            "unsupported": self.counts.unsupported,
        }
        # `counts.findings` needs no check: ScanCounts already ties the total to the split.
        if counted != recorded:
            raise ValueError(f"counts {recorded} do not describe the {len(self.findings)} findings")
        return self


def _check_command(
    status: VerifyStatus, reason: VerifyReason | None, exit_code: int | None
) -> None:
    """What a row about one command may not say; shared so result and record cannot disagree."""
    if status == "not_run":
        raise ValueError("a command result is what running a command produced")
    if (reason is None) != (status == "pass"):
        raise ValueError(f"{status!r} and reason {reason!r} cannot both be right")
    if reason is not None and reason not in COMMAND_REASONS:
        raise ValueError(f"{reason!r} is a statement about the run, not about a command")
    # A command killed at its deadline may exit 0, and that code is not a verdict.
    if reason != "timeout" and (exit_code == 0) != (status == "pass"):
        raise ValueError(f"exit code {exit_code!r} does not read as {status!r}")
    if (exit_code is None) != (reason == "command_not_executable"):
        raise ValueError("a command has no exit code exactly when it never became a process")


def _check_phase(status: VerifyStatus, reason: VerifyReason | None, commands: int) -> None:
    """What one phase may conclude, held by `VerifyPhase` and by its record."""
    allowed = REASONS_BY_STATUS[status]
    if reason is None:
        if allowed:
            raise ValueError(f"{status!r} says why it is not a pass; this one does not")
    elif reason not in allowed:
        raise ValueError(f"{reason!r} is not a reason a {status!r} can carry")
    if status == "not_run" and commands:
        raise ValueError("nothing ran, so there is no command to record")
    if status == "pass" and not commands:
        raise ValueError("a pass over no command is not a pass")


def _check_gate(
    status: VerifyStatus,
    reason: VerifyReason | None,
    commands: int,
    baseline: VerifyStatus | None,
) -> None:
    """An invariant held by `VerifyResult` and by its record.

    A write refused after the baseline keeps it: nothing is left to verify, and the tests ran.
    """
    if baseline is None:
        if reason == "baseline_failed":
            raise ValueError("baseline_failed over no baseline")
        return
    if status == "not_run":
        if reason == "no_changes_to_verify":
            return
        raise ValueError("nothing ran, so no baseline ran either")
    if baseline == "pass":
        if reason == "baseline_failed":
            raise ValueError("baseline_failed over a baseline that passed")
        return
    if reason == "baseline_failed" and baseline != "fail":
        raise ValueError(f"the baseline did not fail, it was {baseline!r}")
    if status != "inconclusive" or commands:
        raise ValueError(
            "a baseline that did not pass gates the run: the after-phase does not run "
            "and what it would have said is not evidence about the patch"
        )


class CommandResult(_Frozen):
    """One verification command, and what running it produced.

    Only exit 0 passes; no exit code means it never became a process (a killed one's is
    negative); a reason is set exactly when it did not pass, and only a command-level one.
    """

    command: RunnableCommand
    source: CommandSource
    status: VerifyStatus
    reason: VerifyReason | None = None
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    output: str = ""
    truncated: bool = False
    junit: str | None = None
    # Found on PATH inside obelize's own environment; a flag, as a path would name the machine.
    in_obelize_environment: bool = False

    @model_validator(mode="after")
    def _check(self) -> CommandResult:
        _check_command(self.status, self.reason, self.exit_code)
        return self


class VerifyPhase(_Frozen):
    """What one phase concluded: the before-patch run, or the after-patch one.

    `obelize.verify.status` derives status and reason; this refuses pairs that cannot be true,
    including a `pass` over no command.
    """

    status: VerifyStatus
    reason: VerifyReason | None = None
    commands: tuple[CommandResult, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> VerifyPhase:
        _check_phase(self.status, self.reason, len(self.commands))
        return self


class VerifyResult(VerifyPhase):
    """`run.json`'s `verify` object: the after-phase, plus the baseline gate.

    `baseline` is one level deep. A baseline that did not pass makes the run `inconclusive` and
    skips the after-phase; `baseline_failed` needs a baseline that failed, not one
    that timed out.
    """

    baseline: VerifyPhase | None = None

    @model_validator(mode="after")
    def _check_the_baseline(self) -> VerifyResult:
        _check_gate(
            self.status,
            self.reason,
            len(self.commands),
            None if self.baseline is None else self.baseline.status,
        )
        return self


class CommandRecord(_Frozen):
    """One command in `run.json`'s `verify.commands[]`, with its output as a log path."""

    command: RunnableCommand
    source: CommandSource
    status: VerifyStatus
    reason: VerifyReason | None = None
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    truncated: bool = False
    # Run-folder-relative. Output stays out of run.json, which bug reports attach; `CommandResult`
    # holds the output itself and a bare junit file name.
    log: RelativePath | None = None
    junit: RelativePath | None = None
    in_obelize_environment: bool = False

    @classmethod
    def of(cls, result: CommandResult, *, log: str | None, junit: str | None) -> CommandRecord:
        """One result, with the two places the writer put its files."""
        if log is None and result.output:
            raise ValueError(
                f"{result.command!r} printed something and the record names no log; the "
                f"output would be the one thing this row exists to point at"
            )
        return cls(
            command=result.command,
            source=result.source,
            status=result.status,
            reason=result.reason,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            truncated=result.truncated,
            log=log,
            junit=junit,
            in_obelize_environment=result.in_obelize_environment,
        )

    @model_validator(mode="after")
    def _check(self) -> CommandRecord:
        _check_command(self.status, self.reason, self.exit_code)
        return self


class VerifyPhaseRecord(_Frozen):
    """One verification phase as `run.json` records it, with command output as log paths."""

    status: VerifyStatus
    reason: VerifyReason | None = None
    commands: tuple[CommandRecord, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> VerifyPhaseRecord:
        _check_phase(self.status, self.reason, len(self.commands))
        return self


class VerifyRecord(VerifyPhaseRecord):
    """The `verify` object of `run.json`: the after-patch phase plus the baseline that gates it."""

    baseline: VerifyPhaseRecord | None = None

    @model_validator(mode="after")
    def _check_the_baseline(self) -> VerifyRecord:
        _check_gate(
            self.status,
            self.reason,
            len(self.commands),
            None if self.baseline is None else self.baseline.status,
        )
        return self


class FileEdit(_Frozen):
    """One file whose bytes a run would change (`plan.json`) or changed (`run.json`)."""

    # One shape for both documents, so a dry run and an apply compare row for row.
    path: RelativePath
    before_sha256: Sha256
    after_sha256: Sha256
    hunks: int = Field(ge=1)
    rules: tuple[str, ...]
    # The `model/proposals-<n>.json` behind this file, as `rules` traces a pack edit; at most one
    # per file per run.
    proposals: tuple[int, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> FileEdit:
        if self.before_sha256 == self.after_sha256:
            raise ValueError(
                f"{self.path} is recorded as edited and its bytes did not change; a file "
                f"nothing changed is not an edit, it is the absence of one"
            )
        if not self.rules and not self.proposals:
            raise ValueError(
                f"{self.path} was rewritten by nothing; an applied hunk with neither a rule "
                f"nor a proposal behind it is a hunk no reviewer can trace to anything"
            )
        if self.rules and self.proposals:
            raise ValueError(
                f"{self.path} names both a pack rule and a model proposal; a file a rule "
                f"rewrote has no withheld finding, so nothing in it was asked about"
            )
        if any(number < 1 for number in self.proposals):
            raise ValueError(f"proposals are numbered from 1, got {list(self.proposals)}")
        _sorted_unique(self.rules, "rules")
        _sorted_unique(self.proposals, "proposals")
        return self


class PlanDocument(_Frozen):
    """The `plan.json` document: what a run would write, whether or not it wrote it."""

    # Nothing time-derived and no counts: unlike findings.json it never leaves a run folder,
    # where run.json holds both.
    obelize_version: str
    pack: PackRef
    files: tuple[FileEdit, ...] = ()
    edits: tuple[Edit, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> PlanDocument:
        paths = [row.path for row in self.files]
        if paths != sorted(paths):
            raise ValueError("the files a run would write are written in path order")
        if len(set(paths)) != len(paths):
            raise ValueError("one file is one row; two rows for one path is two answers")
        keys = [(row.path, row.line) for row in self.edits]
        if keys != sorted(keys):
            raise ValueError("edits are written in document order; sort before emitting")
        return self


# `verify` and `undo` update an existing run folder and never create one, so neither is a mode.
RunMode = Literal["scan", "plan", "apply"]
RUN_MODES: frozenset[RunMode] = frozenset(get_args(RunMode))

# The modes that ran the rules, so they report `auto` rather than the scan's `eligible`.
FIX_MODES: frozenset[RunMode] = frozenset({"plan", "apply"})

# SCAN_VOCABULARY.md's repository status: below Python 3.10 the new distribution
# cannot install, so the run reports findings and proposes no migration.
BlockedReason = Literal["runtime_unsupported"]
BLOCKED_REASONS: frozenset[BlockedReason] = frozenset(get_args(BlockedReason))

# `SkipReason` plus `obelize.scan.parse.ReadRefusal`, written out because that module imports
# this one; tests/unit/test_models.py asserts the union.
LimitationCode = Literal[
    "file_too_large",
    "input_does_not_parse",
    "missing",
    "not_a_file",
    "outside_root",
    "submodule",
    "symlink",
    "unreadable",
    "unusable_name",
]
LIMITATION_CODES: frozenset[LimitationCode] = frozenset(get_args(LimitationCode))

# `fsutil.WriteRefusal` plus the evidence writer's tree-level `tree_dirty` and
# `tree_unknown`. Deliberately not `LimitationCode`: that is what a run could not look at, this
# what it declined to do. Written out for the import direction; test_models.py asserts the union.
RefusalCode = Literal[
    "file_changed_since_read",
    "missing",
    "not_a_file",
    "outside_root",
    "symlink",
    "tree_dirty",
    "tree_unknown",
    "unreadable",
]
REFUSAL_CODES: frozenset[RefusalCode] = frozenset(get_args(RefusalCode))

# Why `obelize undo` skipped a file (docs/CLI.md).
# Five are fsutil's path guard. `hash_mismatch` (edited after the run) is deliberately not
# `file_changed_since_read`, which refuses a whole apply whose plan went stale mid-run.
UndoSkip = Literal[
    "hash_mismatch",
    "missing",
    "not_a_file",
    "outside_root",
    "snapshot_unusable",
    "symlink",
    "unreadable",
]
UNDO_SKIPS: frozenset[UndoSkip] = frozenset(get_args(UndoSkip))

# No `partly`: a rename either put the bytes back or did not.
UndoOutcome = Literal["reverted", "skipped"]
UNDO_OUTCOMES: frozenset[UndoOutcome] = frozenset(get_args(UndoOutcome))

# Also declared in `obelize.config` for the import direction; test_config.py asserts they match.
ConfigOrigin = Literal["file", "defaults"]
CONFIG_ORIGINS: frozenset[ConfigOrigin] = frozenset(get_args(ConfigOrigin))

# No pack path is recorded: it could be absolute on the scanning machine (TM-1); the sha256 and
# the copy in the run folder identify the pack.
PackOrigin = Literal["bundled", "file"]
PACK_ORIGINS: frozenset[PackOrigin] = frozenset(get_args(PackOrigin))

# docs/CLI.md's exit codes, shared by every command (test_cli_surface.py checks both ways).
ExitCode = Literal[0, 1, 2, 3, 4, 5, 6, 7]
EXIT_CODES: frozenset[ExitCode] = frozenset(get_args(ExitCode))

# Public: `verify --run <id>` and `undo --run <id>` check the argument before joining it onto a
# path, so an id of any other shape never becomes a directory name (TM-1).
RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")

_INSTANT = re.compile(r"^[0-9]{4}(-[0-9]{2}){2}T[0-9]{2}(:[0-9]{2}){2}Z$")


def _run_id(value: str) -> str:
    """The folder name: sorts chronologically, and has no colon, which Windows file names forbid."""
    if not RUN_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{value!r} is not a run id of the form 20260917T142530Z-3f9a1c72")
    return value


def _instant(value: str) -> str:
    if not _INSTANT.fullmatch(value):
        raise ValueError(
            f"{value!r} is not an ISO 8601 UTC timestamp of the form 2026-09-18T09:14:07Z"
        )
    return value


RunId = Annotated[str, AfterValidator(_run_id)]
Instant = Annotated[str, AfterValidator(_instant)]


class RunPython(_Frozen):
    """The interpreter that ran, deliberately without its path, which would name the machine."""

    version: str
    implementation: str


class RunPlatform(_Frozen):
    """The operating system and machine the run used, as Python's `platform` module reports them."""

    system: str
    release: str
    machine: str


class RunPack(_Frozen):
    """The pack a run used: which one, its own version, and its exact bytes."""

    id: str
    pack_version: str
    sha256: Sha256
    source: PackOrigin


class RunConfig(_Frozen):
    """The configuration the run used, flags over file, without the exclusions every run applies."""

    source: ConfigOrigin
    include: str
    exclude: tuple[str, ...] = ()
    max_file_bytes: int = Field(gt=0)


class RunCounts(ScanCounts):
    """The finding counts of a run by status, plus its warning count."""

    # A scan reports `eligible`, a plan or apply `auto`, never both (RunRecord checks which).
    auto: int = Field(default=0, ge=0)
    warnings: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check(self) -> RunCounts:
        """Replaces the parent check: the split adds `auto`, which excludes `eligible`."""
        if self.files_parsed > self.files_selected:
            raise ValueError("more files were parsed than were selected")
        split = self.eligible + self.auto + self.needs_review + self.unsupported + self.not_a_usage
        if split != self.findings:
            raise ValueError(f"the status split sums to {split}, and there are {self.findings}")
        if self.eligible and self.auto:
            raise ValueError(
                "a run reports `eligible` or `auto` and never both: one says no scan-time "
                "rule withheld the row and the other says a rule rewrote it"
            )
        return self


class Withheld(_Frozen):
    """One finding the run withheld, with its bail, so `run.json` alone answers why not."""

    path: RelativePath
    line: int = Field(ge=1)
    # Null for the `parse_error` row of an unparsable file, which resolved no usage.
    symbol: str | None = None
    bail: BailCode
    caused_by: tuple[BailCode, ...] | None = None

    @classmethod
    def of(cls, finding: Finding) -> Withheld:
        """The row for a withheld finding; refuses one that withholds nothing."""
        if finding.bail is None:
            raise ValueError(
                f"{finding.path}:{finding.line} is {finding.scan_status!r} and withholds "
                f"nothing, so there is no row for it in `withheld[]`"
            )
        return cls(
            path=finding.path,
            line=finding.line,
            symbol=finding.symbol,
            bail=finding.bail,
            caused_by=finding.caused_by,
        )

    @model_validator(mode="after")
    def _check(self) -> Withheld:
        _check_caused_by(self.bail, self.caused_by, "caused_by")
        return self


class RunLimitation(_Frozen):
    """One thing the run could not look at, so a small count never reads as a clean repository."""

    code: LimitationCode
    path: RelativePath | None = None
    detail: str


class RunRefusal(_Frozen):
    """One file the run planned to write and did not, and the code for why."""

    code: RefusalCode
    path: RelativePath | None = None
    detail: str

    @model_validator(mode="after")
    def _check(self) -> RunRefusal:
        if (self.code in ("tree_dirty", "tree_unknown")) != (self.path is None):
            raise ValueError(
                "`tree_dirty` and `tree_unknown` are the refusals about the repository and "
                "name no path; every other one is about the file it names"
            )
        return self


class RunModel(_Frozen):
    """The `model` object of `run.json`: what a run that consulted a model asked and got back."""

    provider: ProviderName
    # `ModelConfig.host`, never the URL, whose query can carry a credential.
    host: str
    model: str
    # Proposals that came back, not questions asked.
    proposals: int = Field(ge=0)
    # Passed every guard and were written, which needs `--apply` and `--accept-model`.
    accepted: int = Field(ge=0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> RunModel:
        if self.provider == "none":
            raise ValueError(
                "a run with no provider records no model object at all; `none` here would "
                "be a record of a consultation that did not happen"
            )
        if self.accepted > self.proposals:
            raise ValueError(
                f"{self.accepted} of {self.proposals} proposal(s) were written, which is "
                f"more edits than answers"
            )
        return self


class ConsultationSkip(_Frozen):
    """One withheld row a model was not asked about, and the reason why."""

    path: RelativePath
    line: int = Field(ge=1)
    reason: ConsultSkip


class ProposalRecord(_Frozen):
    """The `model/proposals-<n>.json` document: one consultation and what became of it."""

    # Numbered per consultation, not per proposal: an unreachable endpoint still leaves a file.
    index: int = Field(ge=1)
    # The only file the guard lets the proposal edit.
    path: RelativePath
    line: int = Field(ge=1)
    symbol: str | None = None
    # What the deterministic rules refused with; the code is the whole message.
    bail: BailCode
    # The range sent as context, 1-based and inclusive.
    context_start_line: int = Field(ge=1)
    context_end_line: int = Field(ge=1)
    # Of the exact request body, serialised with sorted keys so one question hashes one way.
    prompt_sha256: Sha256
    # Only when `model.log_prompts` is true: a prompt is source code.
    prompt: str | None = None
    provider: ProviderName
    model: str
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    outcome: ProposalOutcome
    failure: ProviderFailure | None = None
    refusal: GuardRefusal | None = None
    # One line from whichever decided; redacted before it is cut, as endpoint text is untrusted.
    detail: str | None = None
    proposal: EditProposal | None = None

    @model_validator(mode="after")
    def _check(self) -> ProposalRecord:
        if self.context_end_line < self.context_start_line:
            raise ValueError(
                f"the context is lines {self.context_start_line}..{self.context_end_line}, "
                f"which is no range at all"
            )
        if (self.failure is not None) != (self.outcome == "unanswered"):
            raise ValueError(
                "`unanswered` is exactly the outcome that carries a `ProviderFailure`, and "
                "every other one is an answer that arrived"
            )
        if (self.refusal is not None) != (self.outcome == "guard_refused"):
            raise ValueError(
                "`guard_refused` is exactly the outcome that carries a `GuardRefusal`; a "
                "proposal that was not refused was not refused for a reason either"
            )
        answered = self.outcome not in ("unanswered", "nothing_proposed")
        if (self.proposal is not None) != answered:
            raise ValueError(
                f"outcome={self.outcome!r} "
                f"{'needs' if answered else 'has'} a proposal "
                f"{'and carries none' if answered else 'and should not'}"
            )
        return self


class ModelDocument(_Frozen):
    """The `model/model.json` index: the run's model summary and the rows never put to a model."""

    # No copy of the proposals: they live in the numbered files and may hold source code.
    obelize_version: str
    summary: RunModel
    # Questions asked, and so the numbered files: `model/proposals-1.json` onward.
    consulted: int = Field(ge=0)
    skipped: tuple[ConsultationSkip, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> ModelDocument:
        if self.summary.proposals > self.consulted:
            raise ValueError(
                f"{self.summary.proposals} proposal(s) came back from {self.consulted} "
                f"question(s); one question is answered at most once"
            )
        keys = [(row.path, row.line) for row in self.skipped]
        if keys != sorted(keys):
            raise ValueError("skipped rows follow the findings, which are in document order")
        return self


class RunTimings(_Frozen):
    """The run's wall-clock times, kept here alone so everything else compares between two runs."""

    started_at: Instant
    finished_at: Instant
    total_ms: int = Field(ge=0)
    scan_ms: int | None = Field(default=None, ge=0)
    plan_ms: int | None = Field(default=None, ge=0)
    apply_ms: int | None = Field(default=None, ge=0)
    verify_ms: int | None = Field(default=None, ge=0)
    # The consultation; present exactly when a model was asked something.
    model_ms: int | None = Field(default=None, ge=0)


class RunJournal(_Frozen):
    """`journal.json`: the plan's file edits, on disk before an apply writes any of them.

    Both copies of each file sit beside it. A finished run replaces it with `run.json`; an
    interrupted one leaves it for `obelize undo`.
    """

    run_id: RunId
    file_edits: tuple[FileEdit, ...]


class RunRecord(_Frozen):
    """The `run.json` document: the index of one run folder."""

    # Fields match docs/RUN_FOLDER.md's table (test_run_folder_contract.py); `mode` decides which
    # may be set, and one that does not apply is null or empty, never absent.
    run_id: RunId
    obelize_version: str
    mode: RunMode
    exit_code: ExitCode
    blocked: BlockedReason | None = None
    argv: tuple[str, ...] = ()
    python: RunPython
    platform: RunPlatform
    git_sha: str | None = None
    git_branch: str | None = None
    git_dirty: bool | None = False
    pack: RunPack
    config: RunConfig
    counts: RunCounts
    file_edits: tuple[FileEdit, ...] = ()
    refused: tuple[RunRefusal, ...] = ()
    idempotent: bool | None = None
    withheld: tuple[Withheld, ...] = ()
    verify: VerifyRecord | None = None
    model: RunModel | None = None
    limitations: tuple[RunLimitation, ...] = ()
    timings: RunTimings

    @model_validator(mode="after")
    def _check(self) -> RunRecord:
        self._check_order()
        self._check_the_split()
        self._check_the_mode()
        self._check_the_clock()
        return self

    def _check_order(self) -> None:
        keys = [(row.path, row.line) for row in self.withheld]
        if keys != sorted(keys):
            raise ValueError("withheld rows follow the findings, which are in document order")
        limits = [
            ((row.path or "").encode("utf-8"), row.code, row.detail) for row in self.limitations
        ]
        if limits != sorted(limits):
            raise ValueError("limitations are written sorted, so two runs can be compared")
        written = [row.path for row in self.file_edits]
        if written != sorted(written):
            raise ValueError("file_edits is written in path order, the order the writes went in")
        if len(set(written)) != len(written):
            raise ValueError("one file is written once; two rows for one path is two answers")
        refusals = [((row.path or ""), row.code) for row in self.refused]
        if refusals != sorted(refusals):
            raise ValueError("refusals are written sorted, so two runs can be compared")

    def _check_the_split(self) -> None:
        """Which of `eligible` and `auto` this mode is entitled to report."""
        if self.mode in FIX_MODES:
            if self.counts.eligible:
                raise ValueError(
                    f"a {self.mode!r} has run the rules, so its rows are graded `auto` or "
                    f"withheld; `eligible` is what a scan says before any rule was tried"
                )
            return
        if self.counts.auto:
            raise ValueError("a scan has applied no rule, so it can claim no `auto` row")
        if self.counts.warnings:
            raise ValueError("a scan plans no edit, so it can carry no warning")

    def _check_the_mode(self) -> None:
        """What each mode may say about the disk and about the verification."""
        if self.mode == "scan":
            if self.file_edits or self.refused or self.idempotent is not None:
                raise ValueError("a scan writes no file, so it refuses none and changes none")
            if self.verify is not None:
                raise ValueError("a scan has no verification phase")
            if self.model is not None:
                raise ValueError(
                    "a scan plans no edit, so there is nothing for a model to propose one "
                    "for and nothing to consult one about"
                )
            return
        if self.verify is None:
            raise ValueError(
                f"a {self.mode!r} always records a verification, including the runs where "
                f"nothing ran: a missing verdict is an outcome and not an absent field"
            )
        if self.model is not None and self.model.accepted and self.mode != "apply":
            raise ValueError(
                f"a {self.mode!r} run recorded {self.model.accepted} accepted proposal(s), "
                f"and a proposal is accepted by being written"
            )
        proposed = {number for row in self.file_edits for number in row.proposals}
        if proposed and (self.model is None or len(proposed) != self.model.accepted):
            raise ValueError(
                f"{len(proposed)} file edit(s) name a proposal and `model` records "
                f"{None if self.model is None else self.model.accepted} accepted; the two "
                f"count the same writes"
            )
        if self.mode == "plan":
            if self.file_edits or self.refused or self.idempotent is not None:
                raise ValueError("a plan writes nothing; what it would write is plan.json")
            if (self.verify.status, self.verify.reason) != ("not_run", "dry_run"):
                raise ValueError(
                    "a dry run has nothing to verify and records `not_run` with the reason "
                    "`dry_run`"
                )
            return
        if self.idempotent is None:
            raise ValueError("an apply says whether it changed anything")
        if self.idempotent != (not self.file_edits):
            raise ValueError(
                f"idempotent is {self.idempotent} over {len(self.file_edits)} written file(s); "
                f"it records what happened to the bytes and nothing else"
            )

    def _check_the_clock(self) -> None:
        """A phase that did not run has no duration, which is `timings`' rule.

        A baseline under `not_run` ran before a refused write, so its verification ran.
        """
        verified = self.verify is not None and (
            self.verify.status != "not_run" or self.verify.baseline is not None
        )
        for name, expected in (
            ("plan_ms", self.mode in FIX_MODES),
            ("apply_ms", self.mode == "apply"),
            ("verify_ms", verified),
            ("model_ms", self.model is not None),
        ):
            if (getattr(self.timings, name) is not None) != expected:
                raise ValueError(
                    f"{name} is the duration of a phase that ran, and a {self.mode!r} run "
                    f"{'ran' if expected else 'did not run'} that one"
                )


class UndoFile(_Frozen):
    """One file `obelize undo` was asked to put back, and what became of it."""

    path: RelativePath
    outcome: UndoOutcome
    reason: UndoSkip | None = None
    recorded_sha256: Sha256
    current_sha256: Sha256 | None = None
    # The pre-migration copy in the run folder, recorded even on a skip so the refusal says where
    # the original bytes are.
    snapshot: RelativePath

    @model_validator(mode="after")
    def _check(self) -> UndoFile:
        if (self.reason is None) != (self.outcome == "reverted"):
            raise ValueError(
                f"{self.path} is {self.outcome!r} with reason {self.reason!r}; a skip says "
                f"why and a revert has nothing to say"
            )
        if self.reason == "hash_mismatch":
            if self.current_sha256 in (None, self.recorded_sha256):
                raise ValueError(
                    f"{self.path} is `hash_mismatch` and the hash on the disk is "
                    f"{'not recorded' if self.current_sha256 is None else 'the recorded one'}; "
                    f"that code is exactly the case where the two differ"
                )
            return self
        if self.current_sha256 not in (None, self.recorded_sha256):
            raise ValueError(
                f"{self.path} is {self.outcome!r} over bytes that are neither the ones the "
                f"run wrote nor unreadable; the only word for that is `hash_mismatch`"
            )
        if self.outcome == "reverted" and self.current_sha256 is None:
            raise ValueError(f"{self.path} was put back and what it held first is not recorded")
        return self


class UndoRecord(_Frozen):
    """The `undo.json` document one `obelize undo` writes into the run folder it reverted."""

    # `run_id` is the reverted run's. No summary count: `files[]` has a row for every file the run
    # wrote, skipped ones included, and a count could disagree with it.
    run_id: RunId
    obelize_version: str
    exit_code: ExitCode
    argv: tuple[str, ...] = ()
    undone_at: Instant
    files: tuple[UndoFile, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> UndoRecord:
        paths = [row.path for row in self.files]
        if paths != sorted(paths):
            raise ValueError("the files are written in path order, `file_edits[]`'s own order")
        if len(set(paths)) != len(paths):
            raise ValueError("one file is undone once; two rows for one path is two answers")
        reverted = [row for row in self.files if row.outcome == "reverted"]
        if (self.exit_code == 0) != bool(reverted and len(reverted) == len(self.files)):
            raise ValueError(
                f"exit {self.exit_code} over {len(reverted)} of {len(self.files)} file(s) put "
                f"back; `0` is every file reverted and `4` is anything else"
            )
        return self


__all__ = [
    "ATOMICITY_BAIL",
    "BAIL_CODES",
    "BINDING_KINDS",
    "BLOCKED_REASONS",
    "COMMAND_REASONS",
    "COMMAND_SOURCES",
    "CONFIDENCE_REASONS",
    "CONFIG_ORIGINS",
    "CONSULT_SKIPS",
    "DEFAULT_IMPORT_POLICY",
    "DEFAULT_INCLUDE",
    "EDIT_STATUSES",
    "EXIT_CODES",
    "FINDING_KINDS",
    "FIX_MODES",
    "FLAG_ONLY_PATTERNS",
    "GUARD_REFUSALS",
    "IMPORT_BAILS",
    "IMPORT_KINDS",
    "IMPORT_POLICIES",
    "LIMITATION_CODES",
    "NO_VERDICT_EXPECTED",
    "PACK_ORIGINS",
    "PATH_REFUSALS",
    "PROPOSAL_HELD",
    "PROPOSAL_OUTCOMES",
    "PROVIDER_FAILURES",
    "PROVIDER_NAMES",
    "REASONS_BY_STATUS",
    "REFUSAL_CODES",
    "REPO_ATOMICITY_BAIL",
    "RUN_ID_PATTERN",
    "RUN_MODES",
    "SCAN_STATUSES",
    "SKIP_REASONS",
    "UNDO_OUTCOMES",
    "UNDO_SKIPS",
    "VERDICTS",
    "VERIFY_REASONS",
    "VERIFY_STATUSES",
    "VERIFY_STATUS_ORDER",
    "WARNING_CODES",
    "WITHHELD",
    "BailCode",
    "Binding",
    "BindingKind",
    "BlockedReason",
    "CommandRecord",
    "CommandResult",
    "CommandSource",
    "ConfidenceReason",
    "Config",
    "ConfigOrigin",
    "ConfiguredCommand",
    "ConsultSkip",
    "ConsultationSkip",
    "Edit",
    "EditProposal",
    "EditStatus",
    "ExitCode",
    "FileEdit",
    "Finding",
    "FindingKind",
    "FindingsDocument",
    "FlagOnlyPattern",
    "GuardRefusal",
    "ImpactPlan",
    "ImpactPolicy",
    "ImportPolicy",
    "Instant",
    "LimitationCode",
    "ManifestPlan",
    "MethodReturn",
    "ModelConfig",
    "ModelDocument",
    "PackOrigin",
    "PackRef",
    "PlanDocument",
    "PrefilterToken",
    "ProposalOutcome",
    "ProposalRecord",
    "ProvidedModule",
    "ProviderFailure",
    "ProviderName",
    "ReceiverMethods",
    "RefusalCode",
    "RelativePath",
    "RunConfig",
    "RunCounts",
    "RunId",
    "RunJournal",
    "RunLimitation",
    "RunMode",
    "RunModel",
    "RunPack",
    "RunPlatform",
    "RunPython",
    "RunRecord",
    "RunRefusal",
    "RunTimings",
    "RunnableCommand",
    "ScanCounts",
    "ScanSpec",
    "ScanStatus",
    "Sha256",
    "SkipReason",
    "UndoFile",
    "UndoOutcome",
    "UndoRecord",
    "UndoSkip",
    "Verdict",
    "VerifyConfig",
    "VerifyPhase",
    "VerifyPhaseRecord",
    "VerifyReason",
    "VerifyRecord",
    "VerifyResult",
    "VerifyStatus",
    "WarningCode",
    "Withheld",
    "terminal_unsafe",
]
