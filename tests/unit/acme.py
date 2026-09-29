"""An invented SDK for the scan, impact and transform unit tests: Gemini's shape, none of its names.

A rule proved here reads the projection and its own params, never Gemini's spellings. Two changes
of one kind (MEASURE and LOOKUP, FLAGGED and GONE) catch a rule that ignores its own params.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from obelize.impact import planner
from obelize.models import (
    Config,
    Edit,
    ImpactPolicy,
    MethodReturn,
    ProvidedModule,
    ReceiverMethods,
    ScanSpec,
)
from obelize.packs.schema import (
    Change,
    ChatHistory,
    ConfigureToClientChange,
    ConfigureToClientParams,
    FlagOnlyChange,
    FlagOnlyParams,
    GenerativeModelCallsChange,
    GenerativeModelCallsParams,
    Layout,
    ManifestDependencyChange,
    ManifestDependencyParams,
    Match,
    MethodRewrite,
    PackDocument,
    PackSource,
    RenameImportChange,
    RenameImportParams,
    RewriteCallChange,
    RewriteCallParams,
    SafetySettings,
    VersionRange,
)
from obelize.scan import analysis, manifests, parse, runner
from obelize.transforms import base, codemod, registry
from obelize.transforms import manifest as manifest_rules

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from collections.abc import Mapping
    from pathlib import Path

SPEC = ScanSpec(
    pack_id="test/acme",
    pack_version="0.1.0",
    pack_sha256="0" * 64,
    legacy_modules=("acme.sdk",),
    legacy_distribution="acme-sdk",
    new_distribution="acme-client",
    prefilter_tokens=("acme",),
    symbols=(
        "acme.sdk.Config",
        "acme.sdk.Model",
        "acme.sdk.Session.ask",
        "acme.sdk.configure",
        "acme.sdk.lookup",
        "acme.sdk.measure",
        "acme.sdk.protos",
    ),
    client_symbol="acme.sdk.configure",
    constructor_symbols=("acme.sdk.Model",),
    supported_methods=(
        ReceiverMethods(
            receiver="acme.sdk.Model", methods=("chat", "count", "later", "open", "run")
        ),
        ReceiverMethods(receiver="acme.sdk.Session", methods=("ask", "close")),
    ),
    method_returns=(
        MethodReturn(method="acme.sdk.Model.chat", receiver="acme.sdk.Session"),
        MethodReturn(method="acme.sdk.Model.open", receiver="acme.sdk.Session"),
    ),
    removed_attributes=("acme.sdk.Session.log",),
    flag_only_symbols=("acme.sdk.protos",),
    flag_only_patterns=("dynamic_access", "mock_patch_target", "sys_modules_stub"),
    # A module only the legacy distribution installs, for the manifest pass to find.
    transitive_modules=(ProvidedModule(module="acme.wire", distribution="acme-wire"),),
)


def scan(source: str, spec: ScanSpec = SPEC) -> analysis.Analysis:
    """Analyse `source` as if it were a selected, prefiltered file."""
    read = parse.gates("probe.py", source.encode("utf-8"))
    assert read.status == "parsed", read
    return analysis.analyse(read, spec)


def rows(result: analysis.Analysis) -> list[tuple[int, str, str, str | None]]:
    return [
        (finding.line, finding.kind, finding.confidence_reason, finding.symbol)
        for finding in result.findings
    ]


def statuses(result: analysis.Analysis) -> list[tuple[int, str, str | None]]:
    return [(f.line, f.scan_status, f.bail) for f in result.findings]


CHANGE = RenameImportChange(
    id="rename-import",
    kind="rename_import",
    citation="Acme migration notes, 'Imports'",
    fixtures=("fixtures/negative/none.py", "fixtures/positive/one.before.py"),
    preconditions=("import_resolved",),
    params=RenameImportParams(
        from_module="acme.sdk",
        to_module="acme.client",
        # Not the module's last segment (Gemini's is), so the branch the corpus skips is exercised.
        default_alias="acme_client",
        types_alias_fallback="acme_types",
        submodule_map={"types": "acme.client.types", "wire": "acme.client.wire"},
        types_symbol_map={"Config": "RunConfig", "Level": "Level"},
    ),
)


CLIENT = ConfigureToClientChange(
    id="configure-to-client",
    kind="configure_to_client",
    citation="Acme migration notes, 'Authentication'",
    fixtures=("fixtures/negative/none.py", "fixtures/positive/one.before.py"),
    preconditions=("client_available", "no_unknown_kwargs"),
    params=ConfigureToClientParams(
        legacy_symbol="acme.sdk.configure",
        client_symbol="acme.client.Client",
        # Neither `client` nor a prefix of the fallback: fails a rule hard-coding Gemini's names.
        client_name="handle",
        client_name_fallback="acme_handle",
        allowed_kwargs=("credentials", "key"),
        credential_kwarg="key",
        credentials_object_kwarg="credentials",
    ),
)


MODEL = GenerativeModelCallsChange(
    id="model-calls",
    kind="generative_model_calls",
    citation="Acme migration notes, 'Models'",
    fixtures=("fixtures/negative/none.py", "fixtures/positive/one.before.py"),
    preconditions=("client_available", "closed_world_binding", "receiver_resolved"),
    params=GenerativeModelCallsParams(
        ctor_symbol="acme.sdk.Model",
        methods={
            "acme.sdk.Model": ("chat", "count", "later", "open", "run"),
            "acme.sdk.Session": ("ask", "close"),
        },
        method_returns={
            "acme.sdk.Model.chat": "acme.sdk.Session",
            "acme.sdk.Model.open": "acme.sdk.Session",
        },
        generation_config_keys=("heat", "limit"),
        # `guard` is the legacy table and `blocks` the new field: a rule using one for both fails.
        safety=SafetySettings(
            legacy_kwarg="guard",
            legacy_category_key="kind",
            legacy_threshold_key="level",
            legacy_category_class="acme.sdk.types.Rudeness",
            legacy_threshold_class="acme.sdk.types.Block",
            category_map={"rude": "CATEGORY_RUDE"},
            threshold_map={"some": "BLOCK_SOME"},
            category_members=("CATEGORY_RUDE",),
            threshold_members=("BLOCK_ALWAYS", "BLOCK_SOME"),
            setting_class="acme.client.types.Guard",
            category_class="acme.client.types.Rudeness",
            threshold_class="acme.client.types.Block",
            category_kwarg="kind",
            threshold_kwarg="level",
            config_field="blocks",
        ),
        history=ChatHistory(
            role_key="who",
            parts_key="said",
            text_key="words",
            roles=("them", "us"),
        ),
        config_class="acme.client.types.RunConfig",
        default_model_name="acme-1",
        legacy_config_symbol="acme.sdk.Config",
        legacy_config_aliases=("acme.sdk.types.Config",),
        legacy_config_kwarg="settings",
        # `cache` is a constructor keyword with no destination.
        ctor_order=("label", "guard", "settings", "helpers", "preamble", "cache"),
        ctor_model_kwarg="label",
        ctor_config_fields=("preamble",),
        ctor_afc_kwargs=("helpers",),
        model_kwarg="target",
        stream_kwarg="live",
        model_name_prefix="acme/",
        rewrites={
            # `Model.open` and `Session.close` are declared but unwritten on purpose
            # (`receiver_method_unmapped`): one per receiver, as a group is the closure of both.
            "acme.sdk.Model.chat": MethodRewrite(
                new_call="talks.begin",
                history_kwarg="past",
                afc_kwargs=("auto",),
                config_kwarg="options",
            ),
            "acme.sdk.Model.later": MethodRewrite(
                new_call="wait.models.run",
                stream_call="wait.models.run_stream",
                coroutine=True,
                positional_to_kw=("body",),
                config_kwarg="options",
            ),
            "acme.sdk.Model.run": MethodRewrite(
                new_call="models.run",
                stream_call="models.run_stream",
                positional_to_kw=("body",),
                contents_kwarg="body",
                config_kwarg="options",
            ),
            "acme.sdk.Model.count": MethodRewrite(
                new_call="models.count",
                positional_to_kw=("body",),
                semantic_kwargs=("preamble",),
            ),
            # The only rewrite rooted on the receiver, and the only keyword rename.
            "acme.sdk.Session.ask": MethodRewrite(
                root="receiver",
                new_call="post",
                stream_call="post_stream",
                positional_to_kw=("text",),
                arg_map={"text": "note"},
                contents_kwarg="text",
                config_kwarg="options",
            ),
        },
        response_attrs_now_none=("answer",),
        response_legacy_error="LookupError",
        legacy_error_modules=("acme.errors",),
    ),
)


MEASURE = RewriteCallChange(
    id="measure",
    kind="rewrite_call",
    citation="Acme migration notes, 'Measuring'",
    fixtures=("fixtures/negative/none.py", "fixtures/positive/one.before.py"),
    preconditions=("client_available", "import_resolved"),
    params=RewriteCallParams(
        legacy_symbol="acme.sdk.measure",
        new_call="probe.measure",
        # `kind` keeps its name, which a rule that renamed every argument would get wrong.
        arg_map={"body": "text"},
        positional_to_kw=("kind", "body"),
        config_class="acme.client.types.MeasureConfig",
        config_kwarg="opts",
        config_kwargs=("depth", "tone"),
        result_access_flags=("score",),
        legacy_error_modules=("acme.errors",),
    ),
)


LOOKUP = RewriteCallChange(
    id="lookup",
    kind="rewrite_call",
    citation="Acme migration notes, 'Lookups'",
    fixtures=("fixtures/negative/none.py", "fixtures/positive/one.before.py"),
    preconditions=("client_available", "import_resolved"),
    params=RewriteCallParams(
        legacy_symbol="acme.sdk.lookup",
        new_call="registry.fetch",
        positional_to_kw=("tag",),
        # The legacy result's class hinged on this prefix: an unreadable tag cannot be promised.
        dispatch_prefixes={"tag": ("kinds/",)},
        # A field the legacy result had and the new one does not.
        result_attribute_flags=("gone",),
    ),
)


FLAGGED = FlagOnlyChange(
    id="flag-protos",
    kind="flag_only",
    citation="Acme migration notes, 'What did not move'",
    fixtures=("fixtures/negative/none.py", "fixtures/positive/one.before.py"),
    params=FlagOnlyParams(
        message="The protos surface has no counterpart and is reached by name in three ways.",
        suggestion="Port these call sites by hand against the acme-client reference.",
        symbols=("acme.sdk.protos",),
        patterns=("dynamic_access", "mock_patch_target", "sys_modules_stub"),
    ),
)


GONE = FlagOnlyChange(
    id="flag-session-log",
    kind="flag_only",
    citation="Acme migration notes, 'Sessions'",
    fixtures=("fixtures/negative/none.py", "fixtures/positive/one.before.py"),
    params=FlagOnlyParams(
        message="acme-client sessions keep no log attribute.",
        suggestion="Read the transcript from the session's own method instead.",
        attributes=("acme.sdk.Session.log",),
    ),
)


PIN = ManifestDependencyChange(
    id="pin",
    kind="manifest_dependency",
    citation="Acme migration notes, 'Installing'",
    fixtures=("fixtures/negative/none.txt", "fixtures/positive/one.before.txt"),
    params=ManifestDependencyParams(
        from_name="acme-sdk",
        to_name="acme-client",
        # Not Gemini's `>=1`, to catch a hard-coded constant.
        to_spec=">=2",
    ),
)


def declared(
    name: str,
    source: str,
    migration: manifests.Migration,
    *,
    spec: ScanSpec = SPEC,
    change: Change = PIN,
) -> tuple[str, list[Edit]]:
    """Grade one manifest against a hand-written migration and run `change`'s rule.

    The migration alone decides whether the same manifest gets a replacement or an insertion.
    """
    data = source.encode("utf-8")
    plan = manifests.plan(manifests.declarations(name, data), migration, spec)
    active = registry.manifest_rule_for(change)
    assert active is not None, change
    context = manifest_rules.ManifestContext.build(name, data, plan)
    edits = list(active.apply(context))
    return manifest_rules.finish(context).decode("utf-8"), edits


# Every change above in run order: import reserves names, client places the client, model reads
# both. `packs/loader.py` never sees this pack, so its `fixtures` may name files that do not exist.
PACK = PackDocument(
    id="acme/acme-sdk-to-acme-client",
    pack_version="0.1.0",
    provider="acme",
    language="python",
    source=PackSource(
        type="official_guide",
        url="https://example.invalid/acme",
        retrieved_at="2026-09-20",
    ),
    **{"from": VersionRange(package="acme-sdk", version="==0.1.0")},
    to=VersionRange(package="acme-client", version=">=2"),
    match=Match(imports=("acme.sdk",), prefilter_tokens=("acme",)),
    changes=(CHANGE, CLIENT, MODEL, MEASURE, LOOKUP, FLAGGED, GONE, PIN),
    limitations=("Invented for the tests; no SDK of this name exists.",),
)


def repository(
    root: Path,
    files: Mapping[str, str],
    *,
    spec: ScanSpec = SPEC,
    pack: PackDocument = PACK,
    policy: ImpactPolicy | None = None,
    sources: Mapping[str, bytes] | None = None,
) -> codemod.Run:
    """Write `files` under `root`, scan the tree the real way, and run the whole pack over it.

    `sources` overrides what the driver is handed, to test a caller that hands over the wrong set.
    """
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    scanned = runner.scan(root, Config(), spec, policy, jobs=1)
    if sources is None:
        sources = {name: (root / name).read_bytes() for name in sorted(files)}
    return codemod.run(scanned, sources, pack, spec, policy)


def transform(
    source: str,
    *changes: Change,
    spec: ScanSpec = SPEC,
    layout: Layout | None = None,
    policy: ImpactPolicy | None = None,
) -> tuple[str, list[Edit]]:
    """Scan `source` as one selected file, run the rules over its real plan, return both.

    Under the default `atomic` policy a rule never sees a group the scan refused; `dual` does.
    """
    read = parse.gates("probe.py", source.encode("utf-8"))
    assert read.module is not None, read
    plan = planner.plan(analysis.analyse(read, spec), spec, policy)
    active = [rule for rule in map(registry.rule_for, changes or (CHANGE,)) if rule is not None]
    context = base.RuleContext.build(plan, read.module, spec, active, layout)
    edits = [row for rule in active for row in rule.apply(context)]
    return base.finish(context).code, edits
