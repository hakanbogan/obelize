"""What the Gemini pack claims about the two SDKs, checked against both.

SDK names are checked against `google.genai`'s own members (hence the dev dependency), never by
construction, which fabricates unknown enum members.
"""

from __future__ import annotations

import importlib
import inspect
import typing
from importlib.metadata import version
from types import SimpleNamespace
from typing import cast

import pytest
from google.genai import chats, files, models, types
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import ValidationError

from obelize.models import ReceiverMethods, bounds
from obelize.packs import loader, schema

BUNDLED_ID = "gemini/google-generativeai-to-google-genai"
BUNDLED = loader.load(BUNDLED_ID)
PACK = BUNDLED.pack


def _params(kind: str) -> list[typing.Any]:
    return [change.params for change in PACK.changes if change.kind == kind]


MODEL_PARAMS = _params("generative_model_calls")
RENAME_PARAMS = _params("rename_import")
CALL_PARAMS = _params("rewrite_call")


def test_the_pack_is_the_migration_adr_001_chose() -> None:
    assert PACK.from_.package == "google-generativeai"
    assert PACK.to.package == "google-genai"
    assert PACK.match.imports == ("google.generativeai",)
    assert PACK.match.prefilter_tokens == ("generativeai",)


def test_the_installed_sdk_is_inside_the_range_the_pack_migrates_to() -> None:
    """The weekly job runs this file on the floor and on the newest release as well."""
    assert version("google-genai") in SpecifierSet(PACK.to.version)
    assert bounds(SpecifierSet(PACK.to.version))[0] == Version("1.55")


def test_the_safety_tables_are_asserted_against_members_and_not_construction() -> None:
    """The control: construction accepts invented names with only a warning."""
    with pytest.warns(UserWarning, match="is not a valid") as captured:
        fabricated = types.SafetySetting(
            category="HARM_CATEGORY_HATE",
            threshold="BLOCK_EVERYTHING",
        )
    assert [str(warning.message) for warning in captured] == [
        "HARM_CATEGORY_HATE is not a valid HarmCategory",
        "BLOCK_EVERYTHING is not a valid HarmBlockThreshold",
    ]
    assert fabricated.category is not None
    assert "HARM_CATEGORY_HATE" not in types.HarmCategory.__members__
    assert "BLOCK_EVERYTHING" not in types.HarmBlockThreshold.__members__

    for params in MODEL_PARAMS:
        for value in params.safety.category_map.values():
            assert value in types.HarmCategory.__members__, value
        for value in params.safety.threshold_map.values():
            assert value in types.HarmBlockThreshold.__members__, value
        # `OFF` is a member of both enums but never a string the legacy lookup took.
        for member in params.safety.category_members:
            assert member in types.HarmCategory.__members__, member
        for member in params.safety.threshold_members:
            assert member in types.HarmBlockThreshold.__members__, member
        assert "OFF" in params.safety.threshold_members
        assert "off" not in params.safety.threshold_map


def test_the_safety_tables_refuse_what_the_legacy_lookup_refused() -> None:
    """The three keys PACK_SPEC names, and the canonical long forms it requires."""
    for params in MODEL_PARAMS:
        assert "dangerous_content" not in params.safety.category_map
        assert "off" not in params.safety.threshold_map
        assert "none" not in params.safety.threshold_map
        # Long forms are keys too: code writes them and the legacy SDK looked up `value.lower()`.
        for member in types.HarmCategory.__members__:
            if member in set(params.safety.category_map.values()):
                assert member.lower() in params.safety.category_map, member


def test_the_generation_config_keys_are_the_fifteen_that_exist_on_both_sides() -> None:
    fields = types.GenerateContentConfig.model_fields
    for params in MODEL_PARAMS:
        assert len(params.generation_config_keys) == 15
        missing = [key for key in params.generation_config_keys if key not in fields]
        assert missing == [], missing
        # `seed` exists on the new config, so mapping it looks free, but it was never a legacy key.
        assert "seed" in fields
        assert "seed" not in params.generation_config_keys


# The class a `new_call` is a method of, by the service it is spelled on.
SERVICES: dict[str, type] = {
    "models": models.Models,
    "aio.models": models.AsyncModels,
    "chats": chats.Chats,
    "files": files.Files,
}


def _method(path: str, root: str) -> typing.Callable[..., typing.Any]:
    if root == "receiver":
        return cast("typing.Callable[..., typing.Any]", getattr(chats.Chat, path))
    service, _, name = path.rpartition(".")
    return cast("typing.Callable[..., typing.Any]", getattr(SERVICES[service], name))


def _keywords(path: str, root: str, names: set[str], config: str | None) -> None:
    """Every keyword a rule writes is one the method takes, by name."""
    taken = inspect.signature(_method(path, root)).parameters
    named = {*names, *([config] if config else [])}
    missing = sorted(
        name
        for name in named
        if name not in taken
        or taken[name].kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.VAR_POSITIONAL}
    )
    assert missing == [], f"{path} takes no keyword {missing}"


def test_every_call_the_pack_writes_takes_the_keywords_it_writes() -> None:
    """A name that moved or was renamed in a later release is a `TypeError` after migration."""
    for params in MODEL_PARAMS:
        for rewrite in params.rewrites.values():
            names = {rewrite.arg_map.get(name, name) for name in rewrite.positional_to_kw}
            if rewrite.history_kwarg:
                names.add(rewrite.arg_map.get(rewrite.history_kwarg, rewrite.history_kwarg))
            if rewrite.root == "client":
                names.add(params.model_kwarg)
            for path in (rewrite.new_call, rewrite.stream_call):
                if path:
                    _keywords(path, rewrite.root, names, rewrite.config_kwarg)
    for call in CALL_PARAMS:
        names = {call.arg_map.get(name, name) for name in (*call.positional_to_kw, *call.keywords)}
        _keywords(call.new_call, "client", names, call.config_kwarg)


def test_the_fields_the_pack_moves_into_a_config_are_fields_of_it() -> None:
    for params in MODEL_PARAMS:
        fields = types.GenerateContentConfig.model_fields
        assert set(params.ctor_config_fields) <= set(fields)
    for call in CALL_PARAMS:
        if call.config_class:
            config = getattr(types, call.config_class.rpartition(".")[2])
            assert set(call.config_kwargs) <= set(config.model_fields), call.legacy_symbol


@pytest.mark.parametrize("role", [None, "user"])
def test_a_mapping_system_instruction_is_taken_only_with_text_parts(role: str | None) -> None:
    """The legacy constructor (0.8.6) coerced `{"parts": ["hi"]}`; this config validates it."""
    turn: dict[str, typing.Any] = {} if role is None else {"role": role}
    kept = types.GenerateContentConfig(system_instruction={**turn, "parts": [{"text": "hi"}]})
    assert kept.system_instruction is not None
    with pytest.raises(ValidationError):
        types.GenerateContentConfig(system_instruction={**turn, "parts": ["hi"]})


# google-generativeai 0.8.6, `embedding._EMBEDDING_TASK_TYPE`: its string keys, which `to_task_type`
# looks up lower-cased, and the `protos.TaskType` member each one is. It took integers and members
# as well; the new `EmbedContentConfig.task_type` is a plain string sent as given.
LEGACY_TASK_TYPES = {
    "classification": "CLASSIFICATION",
    "clustering": "CLUSTERING",
    "document": "RETRIEVAL_DOCUMENT",
    "fact_verification": "FACT_VERIFICATION",
    "qa": "QUESTION_ANSWERING",
    "question_answering": "QUESTION_ANSWERING",
    "query": "RETRIEVAL_QUERY",
    "retrieval_document": "RETRIEVAL_DOCUMENT",
    "retrieval_query": "RETRIEVAL_QUERY",
    "semantic_similarity": "SEMANTIC_SIMILARITY",
    "similarity": "SEMANTIC_SIMILARITY",
    "task_type_unspecified": "TASK_TYPE_UNSPECIFIED",
    "unspecified": "TASK_TYPE_UNSPECIFIED",
    "verification": "FACT_VERIFICATION",
}


def test_the_embedding_task_types_are_the_legacy_table_spelled_as_the_service_reads_them() -> None:
    """The new field is a string with nothing to look it up, so the pack spells it out."""
    annotation = types.EmbedContentConfig.model_fields["task_type"].annotation
    assert set(typing.get_args(annotation)) == {str, type(None)}
    tables = [call.value_maps for call in CALL_PARAMS if "task_type" in call.config_kwargs]
    assert len(tables) == 2
    assert all(table == {"task_type": LEGACY_TASK_TYPES} for table in tables)


def test_every_class_the_pack_names_on_the_new_side_exists() -> None:
    """Attribute lookup, not construction, for the same reason as the safety tables."""
    named = {params.config_class for params in MODEL_PARAMS}
    named |= {
        symbol
        for params in MODEL_PARAMS
        for symbol in (
            params.safety.setting_class,
            params.safety.category_class,
            params.safety.threshold_class,
        )
    }
    named |= {params.config_class for params in CALL_PARAMS if params.config_class}
    for params in RENAME_PARAMS:
        named |= set(params.submodule_map.values())
        for key, target in params.symbol_map.items():
            owner, _, _ = key.rpartition(".")
            named.add(f"{params.submodule_map.get(owner, params.to_module)}.{target}")
    for symbol in sorted(named):
        module_path, _, attribute = symbol.rpartition(".")
        try:
            module = importlib.import_module(module_path)
        except ImportError:
            module = importlib.import_module(symbol)
            continue
        assert hasattr(module, attribute), f"{symbol} does not exist in the installed SDK"


def test_the_new_module_the_import_rule_targets_is_importable() -> None:
    for params in RENAME_PARAMS:
        assert importlib.import_module(params.to_module) is not None


def test_generation_config_is_never_mapped_to_itself() -> None:
    """Both names exist in the new SDK, so the class check above cannot catch an identity map."""
    assert hasattr(types, "GenerationConfig")
    assert hasattr(types, "GenerateContentConfig")
    assert "generation_config" not in types.GenerateContentConfig.model_fields
    for params in RENAME_PARAMS:
        assert params.symbol_map["types.GenerationConfig"] == "GenerateContentConfig"


def test_the_new_call_returns_one_model_class_where_the_legacy_one_returned_two() -> None:
    """A tuned name comes back as the wrong class without error, so only `models/` carries."""
    from google.genai import _api_client, _transformers, models

    # `t_model` reads only `vertexai`; a real client would need a key and a network.
    client = cast("_api_client.BaseApiClient", SimpleNamespace(vertexai=False))
    assert _transformers.t_model(client, "models/gemini-1.5-flash") == "models/gemini-1.5-flash"
    assert _transformers.t_model(client, "tunedModels/mine") == "tunedModels/mine"
    assert typing.get_type_hints(models.Models.get)["return"] is types.Model
    assert hasattr(types, "TunedModel"), "the class exists; models.get is just never it"
    prefixes = {
        parameter: values
        for params in CALL_PARAMS
        for parameter, values in params.dispatch_prefixes.items()
    }
    assert prefixes == {"name": ("models/",)}


def test_the_files_calls_take_a_handle_as_well_as_a_name() -> None:
    """`t_file_name` reads `.name` off a `types.File`; other handles fail, hence the limitation."""
    from google.genai import _transformers

    assert _transformers.t_file_name(types.File(name="files/abc123")) == "abc123"
    assert _transformers.t_file_name("files/abc123") == "abc123"

    class Foreign:
        """Shaped like the legacy proto-plus File."""

        name = "files/legacy1"
        uri = "https://generativelanguage.googleapis.com/v1beta/files/legacy1"

    with pytest.raises(ValueError, match="Could not convert object of type"):
        _transformers.t_file_name(cast("types.File", Foreign()))
    text = " ".join(PACK.limitations)
    assert "legacy File, which the new call rejects" in text


def test_the_chat_object_has_no_history_attribute_which_is_why_it_is_flagged() -> None:
    from google.genai import chats

    assert not hasattr(chats.Chat, "history")
    assert hasattr(chats.Chat, "get_history")
    removed = {
        attribute
        for change in PACK.changes
        if isinstance(change, schema.FlagOnlyChange)
        for attribute in change.params.attributes
    }
    assert "google.generativeai.ChatSession.history" in removed


def test_the_hand_written_scan_specs_agree_with_the_bundled_pack() -> None:
    """Two test modules hand-write a `ScanSpec`; this checks their assumptions against the pack."""
    spec = loader.to_scan_spec(BUNDLED)
    assert spec.pack_id == BUNDLED_ID
    assert spec.client_symbol == "google.generativeai.configure"
    assert spec.constructor_symbols == ("google.generativeai.GenerativeModel",)
    assert spec.legacy_distribution == "google-generativeai"
    assert spec.new_distribution == "google-genai"
    assert spec.prefilter_tokens == ("generativeai",)
    model_methods = spec.methods_for("google.generativeai.GenerativeModel")
    assert set(model_methods) >= {
        "count_tokens",
        "generate_content",
        "generate_content_async",
        "start_chat",
    }
    assert ReceiverMethods(
        receiver="google.generativeai.ChatSession",
        methods=("send_message", "send_message_async"),
    ) in list(spec.supported_methods)


def test_the_limitations_say_which_surfaces_the_corpus_never_exercised() -> None:
    """PACK_SPEC requires it: four rule groups ship verified but never field-exercised."""
    text = " ".join(PACK.limitations).lower()
    assert "exercised them zero times" in text
    for surface in ("function calling", "embed_content", "files surface", "models surface"):
        assert surface.lower() in text, surface
