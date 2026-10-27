"""The closed vocabularies: `Literal`s, wire strings unlike an Enum, each with a
`get_args` frozenset where something reads the members. tests/unit/test_models.py checks them
against docs/SCAN_VOCABULARY.md and docs/RUN_FOLDER.md."""

from __future__ import annotations

from typing import Literal, get_args

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
    "receiver_typed_by_class",
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
    "internal_error",
    "file_too_large",
    "runtime_unsupported",
    "legacy_version_unsupported",
    "new_version_unsupported",
    # Resolution and bindings
    "conditional_binding",
    "module_alias_rebound",
    "model_object_escapes",
    "model_object_read_elsewhere",
    "multiple_assignments",
    "class_attr_binding",
    "receiver_unresolved",
    "receiver_method_unmapped",
    "member_overridden",
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
    "lazy_import",
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
    "types_import_typing_only",
    "error_class_changed",
    "pattern_unmatched",
    # External tools
    "external_tool_missing",
    "external_tool_version_unsupported",
    "external_tool_failed",
    "external_tool_timeout",
    "external_tool_size_limit",
    "external_fix_out_of_scope",
    "external_fix_incomplete",
    "external_fix_not_idempotent",
    # The run
    "usage_unmapped",
    "configure_consumed_elsewhere",
    "no_pack_for_usage",
]
BAIL_CODES: frozenset[BailCode] = frozenset(get_args(BailCode))

# What a person changes to move a withheld finding; `SCAN_VOCABULARY.md` section 4 holds the same
# sentences beside each code, and a test keeps the two equal.
BAIL_ACTIONS: dict[BailCode, str] = {
    "roundtrip_mismatch": (
        "Migrate the file by hand; obelize could not read it back byte for byte, so it will not "
        "rewrite it."
    ),
    "input_does_not_parse": (
        "Fix the syntax error in the file, flatten code nested that deep, or fix the Python "
        "requirement in pyproject.toml or setup.cfg, then run again."
    ),
    "output_does_not_parse": (
        "Migrate the file by hand; the rewrite did not parse, so the file was left alone."
    ),
    "output_names_unresolved": (
        "Migrate the file by hand; the rewrite would read a name the module does not bind, so "
        "the file was left alone."
    ),
    "internal_error": "Migrate the file by hand; obelize raised on it, so it was left alone.",
    "file_too_large": "Raise max_file_bytes in .obelize.yml, or migrate the file by hand.",
    "runtime_unsupported": (
        "Raise the Python version the project declares to one the new side of the migration runs "
        "on, then run again."
    ),
    "legacy_version_unsupported": (
        "Declare the legacy distribution in a manifest obelize reads, pinned at or above the "
        "pack's floor, then run again."
    ),
    "new_version_unsupported": (
        "Raise the declaration of the new distribution to a release the pack writes, or remove "
        "it, then run again."
    ),
    "conditional_binding": (
        "Bind the legacy name with one import statement, or migrate its uses by hand."
    ),
    "module_alias_rebound": (
        "Stop rebinding or re-aliasing the legacy module's name, or migrate its uses by hand."
    ),
    "model_object_escapes": (
        "Use the legacy object only as the receiver of its methods, in the file that makes it, "
        "or migrate its uses by hand."
    ),
    "model_object_read_elsewhere": (
        "Stop other modules importing or reading the legacy object, or migrate those modules by "
        "hand."
    ),
    "multiple_assignments": "Assign the name once in its scope, or migrate its uses by hand.",
    "class_attr_binding": (
        "Build the object in a method or at module level, not in the class body, or migrate it "
        "by hand."
    ),
    "receiver_unresolved": (
        "Bind the receiver to a name assigned once from its constructor, or migrate the call by "
        "hand."
    ),
    "receiver_method_unmapped": (
        "Migrate the call by hand; the pack has no rewrite for this method."
    ),
    "pattern_unmatched": (
        "Migrate the call by hand; the pack's pattern for it does not cover this shape of call."
    ),
    "member_overridden": (
        "Migrate the call by hand; a class of this file defines the member itself, so the new "
        "name would run another function."
    ),
    "multiple_configure_calls": "Call configure once in the module, or migrate the module by hand.",
    "client_source_unresolved": (
        "Call configure in this module so a client can be built from it, or migrate the calls "
        "by hand."
    ),
    "client_name_collision": "Rename one of the names client and genai_client, then run again.",
    "client_placement_ambiguous": (
        "Call configure at module level, or move the calls into the function that configures, "
        "or migrate them by hand."
    ),
    "configure_kwargs_unsupported": (
        "Migrate the configure call by hand; the pack does not carry transport, client_options, "
        "client_info or default_metadata over."
    ),
    "credentials_shape_differs": (
        "Migrate the configure call by hand; the new SDK reads credentials in a different shape."
    ),
    "alias_collision": (
        "Rename whatever the file already binds to the new alias or setting name, then run again."
    ),
    "type_symbol_unmapped": "Migrate the import by hand; the pack does not map this type.",
    "from_import_unmigrated_symbol": (
        "Migrate by hand the names on that import line the pack does not map, and the calls "
        "that use them."
    ),
    "local_import": "Move the legacy import to module level, or migrate the code by hand.",
    "lazy_import": (
        "Migrate the lazy import and the code after it by hand; obelize binds no name for it."
    ),
    "star_import": "Replace the star import with named imports, or migrate the module by hand.",
    "file_not_fully_migrated": (
        "Resolve the findings in this file that name the cause; the file stays as it was until "
        "none is left."
    ),
    "repo_not_fully_migrated": (
        "Resolve the withheld findings in the files that still use the legacy distribution, then "
        "run again to change its pin."
    ),
    "transitive_dependency_in_use": (
        "Declare the distribution that provides the module you import, or stop importing it, "
        "then run again."
    ),
    "manifest_code_mismatch": (
        "Make the manifest and the code agree by hand; obelize never edits this declaration."
    ),
    "manifest_pin_shape_unsupported": (
        "Change the pin by hand; obelize edits only a declaration that is a name and a version."
    ),
    "unknown_ctor_kwarg": "Migrate the call by hand; the pack does not know this keyword.",
    "positional_arg_ambiguous": (
        "Give each parameter once and no extra argument, as the call already must, then run again."
    ),
    "default_model_name_required": (
        "Give the constructor a model name, or migrate the call by hand."
    ),
    "generation_config_not_static": (
        "Write generation_config as a literal, or a name assigned once and used only as the "
        "configuration, or migrate it by hand."
    ),
    "safety_settings_not_static": (
        "Write safety_settings as a literal mapping of known categories to known thresholds, "
        "or migrate it by hand."
    ),
    "history_parts_shape_incompatible": (
        "Pass history as a literal list of turns, or migrate the call by hand."
    ),
    "dynamic_stream_flag": "Write stream= as True or False, or migrate the call by hand.",
    "async_stream_await_missing": (
        "Add the missing await before the streaming call, which raises a TypeError without it."
    ),
    "unsupported_kwarg": (
        "Migrate the call by hand; the new call has no counterpart for this keyword."
    ),
    "afc_semantics_differ": (
        "Migrate the call by hand; automatic function calling works differently in the new SDK."
    ),
    "response_shape_changed": (
        "Migrate by hand the code that reads the result; the new call returns a different shape."
    ),
    "count_tokens_config_carries_semantics": (
        "Migrate the count_tokens call by hand; system_instruction and tools change the count."
    ),
    "ctor_argument_not_portable": (
        "Compute the model's name and configuration beforehand into names assigned once, or "
        "migrate the calls by hand."
    ),
    "attribute_removed": (
        "Migrate by hand the code that uses this attribute; the new object has none, or a "
        "method in its place."
    ),
    "flag_only_surface": (
        "Read the pack's suggestion and change the flagged code by hand; obelize never rewrites it."
    ),
    "types_import_typing_only": (
        "Import the module at run time, outside TYPE_CHECKING, or migrate the file by hand."
    ),
    "error_class_changed": (
        "Catch the exception class the new SDK raises in that handler, then run again."
    ),
    "external_tool_missing": (
        "Install the tool the pack's fixer runs, at a release `obelize pack validate` names, then "
        "run again; obelize installs nothing."
    ),
    "external_tool_version_unsupported": (
        "Install a release of the tool that `obelize pack validate` names, then run again."
    ),
    "external_tool_failed": (
        "Migrate the file by hand; the tool did not run or failed on it, so the file was left "
        "alone."
    ),
    "external_tool_timeout": (
        "Migrate the file by hand; the tool did not finish in time, so the file was left alone."
    ),
    "external_tool_size_limit": (
        "Migrate the file by hand; it or the tool's output is larger than obelize takes from a "
        "tool."
    ),
    "external_fix_out_of_scope": (
        "Migrate the file by hand; the tool changed more than the places the scan reported, so "
        "its output was dropped."
    ),
    "external_fix_incomplete": (
        "Migrate by hand what the tool left; its output still names the legacy surface, or it "
        "changed nothing."
    ),
    "external_fix_not_idempotent": (
        "Migrate the file by hand; the tool changed its own output when run again, so its output "
        "was dropped."
    ),
    "usage_unmapped": (
        "Migrate the usage by hand; no rewrite covers it, so the file was left alone."
    ),
    "configure_consumed_elsewhere": (
        "Migrate the modules that rely on this file's configure call, or give each its own, then "
        "run again."
    ),
    "no_pack_for_usage": (
        "Migrate the usage by hand; no migration pack covers this library, so it is listed and "
        "nothing is rewritten."
    ),
}

WarningCode = Literal[
    "client_constructed_eagerly",
    "model_name_looks_prefixed",
    "count_tokens_config_dropped",
    "positional_args_mapped_by_index",
    "history_parts_rewritten",
    "async_stream_await_preserved",
    "response_text_may_be_none",
    "upload_display_name_unset",
]
WARNING_CODES: frozenset[WarningCode] = frozenset(get_args(WarningCode))

# What a terminal prints beside an applied edit; `SCAN_VOCABULARY.md` section 5 holds the same
# sentences, and a test keeps the two equal.
WARNING_MEANINGS: dict[WarningCode, str] = {
    "client_constructed_eagerly": (
        "The new client checks the API key when it is built, and this one is built when the "
        "module is imported, so the import can raise ValueError where configure() did not."
    ),
    "model_name_looks_prefixed": (
        "The model name starts with models/. The new SDK accepts the prefix, so it was left "
        "as written."
    ),
    "count_tokens_config_dropped": (
        "The model's generation_config or safety_settings were not carried into count_tokens."
    ),
    "positional_args_mapped_by_index": (
        "A positional argument past the model name was matched by the old SDK's order "
        "(model_name, safety_settings, generation_config, tools, tool_config, "
        "system_instruction); safety_settings comes first, so check each landed where you "
        "meant."
    ),
    "history_parts_rewritten": (
        'Each string part of the start_chat history literal became {"text": the string}.'
    ),
    "async_stream_await_preserved": (
        "An await before an async streaming call was kept after the rename; dropping it raises "
        "TypeError."
    ),
    "response_text_may_be_none": (
        "The reply's text is read where the old SDK raised ValueError for a reply with none; the "
        "new one returns None, so the value can be None and a handler for that error never runs."
    ),
    "upload_display_name_unset": (
        "The old upload_file set display_name to the file's name when none was given; the new "
        "files.upload sets none, so a read of the uploaded file's display_name is now None."
    ),
}

# An import finding is the statement itself, so only a bail about the statement, the
# whole file or atomicity may withhold it; a downstream group's bail would double-count its defect.
IMPORT_BAILS: frozenset[BailCode] = frozenset(
    {
        "roundtrip_mismatch",
        "output_does_not_parse",
        "output_names_unresolved",
        "internal_error",
        "flag_only_surface",
        "module_alias_rebound",
        "conditional_binding",
        "star_import",
        "local_import",
        "lazy_import",
        "alias_collision",
        "type_symbol_unmapped",
        "from_import_unmigrated_symbol",
        "file_not_fully_migrated",
        "repo_not_fully_migrated",
        "usage_unmapped",
        "no_pack_for_usage",
        "runtime_unsupported",
        "legacy_version_unsupported",
        "new_version_unsupported",
        "external_tool_missing",
        "external_tool_version_unsupported",
        "external_tool_failed",
        "external_tool_timeout",
        "external_tool_size_limit",
        "external_fix_out_of_scope",
        "external_fix_incomplete",
        "external_fix_not_idempotent",
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
FlagOnlyPattern = Literal[
    "mock_patch_target", "dynamic_access", "sys_modules_stub", "environment_write"
]
FLAG_ONLY_PATTERNS: frozenset[FlagOnlyPattern] = frozenset(get_args(FlagOnlyPattern))

# What a call is flagged for (`Finding.evidence`): the word, then the parameter's name (`keyword`,
# `omitted`) or the argument's index (`position`); `spread` takes none.
CallMatch = Literal["keyword", "position", "omitted", "spread"]
CALL_MATCHES: frozenset[CallMatch] = frozenset(get_args(CallMatch))

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
# `await` outside `async` passes libcst and fails `compile()`, which is asked first.
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
    "replaced_text_differs",
    "replacement_carries_redaction",
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


# `verify` and `undo` update an existing run folder and never create one, so neither is a mode.
RunMode = Literal["scan", "plan", "apply"]
RUN_MODES: frozenset[RunMode] = frozenset(get_args(RunMode))

# The modes that ran the rules, so they report `auto` rather than the scan's `eligible`.
FIX_MODES: frozenset[RunMode] = frozenset({"plan", "apply"})

# SCAN_VOCABULARY.md's repository status: the new distribution cannot install on a Python the
# project declares, the legacy pin is outside the pack's range, or a declaration of the new
# distribution admits no release the pack writes, so the run reports findings and proposes no
# migration.
BlockedReason = Literal[
    "runtime_unsupported", "legacy_version_unsupported", "new_version_unsupported"
]

# `SkipReason` plus `obelize.scan.parse.ReadRefusal`, written out because that module imports
# this one; tests/unit/test_models.py asserts the union.
LimitationCode = Literal[
    "file_too_large",
    "input_does_not_parse",
    "internal_error",
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

# Also declared in `obelize.config` for the import direction; test_config.py asserts they match.
ConfigOrigin = Literal["file", "defaults"]
CONFIG_ORIGINS: frozenset[ConfigOrigin] = frozenset(get_args(ConfigOrigin))

# No pack path is recorded: it could be absolute on the scanning machine (TM-1); the sha256 and
# the copy in the run folder identify the pack.
PackOrigin = Literal["bundled", "file", "inventory"]

# The maintained tools an `external_fixer` may run, each as `<tool>:<rule>`. How a tool is run, and
# which releases of it, is in `transforms/fixers.py`, which holds the same set (tested): a pack
# names a fixer and never a command (ADR-074).
FixerId = Literal["ruff:NPY201"]
FIXER_IDS: frozenset[FixerId] = frozenset(get_args(FixerId))

# docs/CLI.md's exit codes, shared by every command (test_cli_surface.py checks both ways).
ExitCode = Literal[0, 1, 2, 3, 4, 5, 6, 7]
EXIT_CODES: frozenset[ExitCode] = frozenset(get_args(ExitCode))


__all__ = [
    "ATOMICITY_BAIL",
    "BAIL_ACTIONS",
    "BAIL_CODES",
    "BINDING_KINDS",
    "CALL_MATCHES",
    "COMMAND_REASONS",
    "COMMAND_SOURCES",
    "CONFIDENCE_REASONS",
    "CONFIG_ORIGINS",
    "CONSULT_SKIPS",
    "DEFAULT_INCLUDE",
    "EDIT_STATUSES",
    "EXIT_CODES",
    "FINDING_KINDS",
    "FIXER_IDS",
    "FIX_MODES",
    "FLAG_ONLY_PATTERNS",
    "GUARD_REFUSALS",
    "IMPORT_BAILS",
    "IMPORT_KINDS",
    "LIMITATION_CODES",
    "NO_VERDICT_EXPECTED",
    "PATH_REFUSALS",
    "PROPOSAL_HELD",
    "PROPOSAL_OUTCOMES",
    "PROVIDER_FAILURES",
    "PROVIDER_NAMES",
    "REASONS_BY_STATUS",
    "REFUSAL_CODES",
    "REPO_ATOMICITY_BAIL",
    "RUN_MODES",
    "SCAN_STATUSES",
    "SKIP_REASONS",
    "UNDO_SKIPS",
    "VERDICTS",
    "VERIFY_REASONS",
    "VERIFY_STATUSES",
    "VERIFY_STATUS_ORDER",
    "WARNING_CODES",
    "WARNING_MEANINGS",
    "WITHHELD",
    "BailCode",
    "BindingKind",
    "BlockedReason",
    "CallMatch",
    "CommandSource",
    "ConfidenceReason",
    "ConfigOrigin",
    "ConsultSkip",
    "EditStatus",
    "ExitCode",
    "FindingKind",
    "FixerId",
    "FlagOnlyPattern",
    "GuardRefusal",
    "LimitationCode",
    "PackOrigin",
    "PathRefusal",
    "ProposalOutcome",
    "ProviderFailure",
    "ProviderName",
    "RefusalCode",
    "RunMode",
    "ScanStatus",
    "SkipReason",
    "UndoOutcome",
    "UndoSkip",
    "Verdict",
    "VerifyReason",
    "VerifyStatus",
    "WarningCode",
]
