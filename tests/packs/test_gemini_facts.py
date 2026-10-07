"""What the Gemini pack claims about the two SDKs, checked against both.

SDK names are checked against `google.genai`'s own members (hence the dev dependency), never by
construction, which fabricates unknown enum members.
"""

from __future__ import annotations

import importlib
import typing
from types import SimpleNamespace
from typing import cast

import pytest
from google.genai import types

from obelize.models import ReceiverMethods
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
