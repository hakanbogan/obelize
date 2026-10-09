"""What the openai pack claims about the two sides, checked against the new release installed.

openai 3.26.0 is pinned in the dev group because these facts are about names, parameters and result
fields, each read from the module and never from the API. 0.28.1 cannot share the environment, so
its half is the snapshot beside this file, which `openai_legacy_check.py` compares to the real
release weekly; the claims about the floor release are checked the same way, by running this
module with `openai==1.109.1` (`.github/workflows/e2e.yml`).
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import typing
from importlib.metadata import metadata, version
from pathlib import Path
from typing import Any

import openai
import openai.types.audio
import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import BaseModel

from obelize.models import bounds
from obelize.packs import loader, schema

BUNDLED = loader.load("openai/openai-0-to-1")
PACK = BUNDLED.pack
SNAPSHOT = json.loads((Path(__file__).parent / "openai_legacy_surface.json").read_text("utf-8"))
REWRITES = {
    change.params.legacy_symbol: change.params
    for change in PACK.changes
    if isinstance(change, schema.RewriteCallChange)
}
SETTINGS = {
    key: new
    for change in PACK.changes
    if isinstance(change, schema.RenameSettingChange)
    for key, new in change.params.settings.items()
}
FLAGGED = {
    symbol
    for change in PACK.changes
    if isinstance(change, schema.FlagOnlyChange)
    for symbol in change.params.symbols
}

# Names of the 0.28.1 module that the new releases define with the meaning they had.
KEPT = {"OpenAIError", "VERSION", "api_key", "organization", "version"}
# Defined by both and read differently, and not listed because code already on the new release
# uses it (`except openai.APIError`): the pack's limitations say what that costs.
SAME_NAME = {"APIError"}
# What `import` leaked into 0.28.1's namespace, and its own tests and scripts: nobody calls these.
NOT_API = {
    "Callable",
    "ContextVar",
    "Optional",
    "TYPE_CHECKING",
    "Union",
    "_openai_scripts",
    "aiohttp",
    "os",
    "sys",
    "tests",
}
# The result type each rewritten call returns, by the call it becomes.
RESULTS: dict[str, type[BaseModel]] = {
    "audio.transcriptions.create": openai.types.audio.Transcription,
    "audio.translations.create": openai.types.audio.Translation,
    "chat.completions.create": openai.types.chat.ChatCompletion,
    "completions.create": openai.types.Completion,
    "embeddings.create": openai.types.CreateEmbeddingResponse,
    "images.generate": openai.types.ImagesResponse,
    "moderations.create": openai.types.ModerationCreateResponse,
}


@pytest.fixture(autouse=True)
def _a_key_the_module_client_is_built_with(monkeypatch: pytest.MonkeyPatch) -> None:
    """The floor release builds its client on first use and refuses to without a key; no call is
    ever made."""
    monkeypatch.setenv("OPENAI_API_KEY", "unused")


def _method(path: str) -> Any:
    target: Any = openai
    for part in path.split("."):
        target = getattr(target, part)
    return target


def _legacy(name: str) -> bool:
    return any(f"openai.{name}" == symbol for symbol in PACK.match.symbols)


def _model(annotation: Any) -> type[BaseModel] | None:
    """The model an annotation holds, looking through `Optional`, `List` and `Annotated`."""
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return annotation
    for argument in typing.get_args(annotation):
        found = _model(argument)
        if found is not None:
            return found
    return None


def test_the_pack_is_the_migration_the_guide_describes() -> None:
    assert PACK.from_.package == PACK.to.package == "openai"
    assert PACK.match.imports == ("openai",)
    assert PACK.match.shared


def test_the_installed_release_is_one_the_pack_migrates_to() -> None:
    assert version("openai") in SpecifierSet(PACK.to.version)


def test_the_python_the_pack_requires_covers_what_the_installed_release_declares() -> None:
    """The floor release decides it: a later one may need more, and the pack must not need less."""
    requires = metadata("openai")["Requires-Python"]
    pythons = [Version(f"3.{minor}") for minor in range(30)]
    needed = {python for python in pythons if python in SpecifierSet(PACK.to.requires_python)}
    declared = {python for python in pythons if python in SpecifierSet(requires)}
    assert declared <= needed
    if Version(version("openai")) == bounds(SpecifierSet(PACK.to.version))[0]:
        assert declared == needed


@pytest.mark.parametrize("name", sorted({*SNAPSHOT["top"], *SNAPSHOT["submodules"]} - NOT_API))
def test_every_name_the_old_release_defined_is_kept_or_named_by_the_pack(name: str) -> None:
    """The closed world of a shared module: what 0.28.1 had and the pack does not list is kept."""
    listed = [symbol for symbol in PACK.match.symbols if symbol.split(".")[1] == name]
    assert bool(listed) != (name in KEPT | SAME_NAME), f"{name} is both kept and legacy, or neither"


@pytest.mark.parametrize("name", sorted(KEPT | SAME_NAME))
def test_a_kept_name_is_defined_by_the_new_release(name: str) -> None:
    assert hasattr(openai, name)


@pytest.mark.parametrize(
    "name",
    sorted(
        name
        for name, kind in SNAPSHOT["top"].items()
        if kind == "class" and _legacy(name) and name != "InvalidRequestError"
    ),
)
def test_a_legacy_resource_is_a_stub_that_raises_when_it_is_called(name: str) -> None:
    """Which is why a call left behind is a runtime failure, and a scan has to find it."""
    stub = getattr(openai, name)
    assert type(stub).__name__ == "APIRemovedInV1Proxy"
    with pytest.raises(Exception, match="no longer supported") as raised:
        stub.create()
    assert type(raised.value).__name__ == "APIRemovedInV1"


@pytest.mark.parametrize(
    "name", sorted(name for name in SNAPSHOT["top"] if _legacy(name) and name.islower())
)
def test_a_legacy_setting_or_module_is_gone_or_means_another_thing(name: str) -> None:
    """Assigning an undefined setting succeeds and changes nothing; `api_type` is read once."""
    if name in {"api_type", "api_version"}:
        assert hasattr(openai, name)
    else:
        assert not hasattr(openai, name)


@pytest.mark.parametrize("name", sorted(SNAPSHOT["submodules"]))
def test_a_legacy_module_cannot_be_imported_from_the_new_release(name: str) -> None:
    if name in NOT_API or not _legacy(name):
        pytest.skip("not a module the pack flags")
    if name == "cli":
        pytest.skip("the 1.x and 2.x releases up to 2.34 ship a different `openai.cli`")
    assert importlib.util.find_spec(f"openai.{name}") is None


def test_a_legacy_exception_is_renamed_or_means_another_class() -> None:
    assert not hasattr(openai, "InvalidRequestError")
    assert not hasattr(openai.APIError, "http_status")


@pytest.mark.parametrize("symbol", sorted(REWRITES))
def test_a_rewritten_call_is_a_keyword_only_method_of_the_module_client(symbol: str) -> None:
    params = REWRITES[symbol]
    method = _method(params.new_call)
    parameters = inspect.signature(method).parameters
    assert all(p.kind is p.KEYWORD_ONLY for p in parameters.values()), params.new_call
    carried = {*params.positional_to_kw, *params.keywords}
    unknown = sorted(carried - set(parameters))
    assert unknown == [], f"{params.new_call} takes none of {unknown}"
    assert not carried & {"stream", "timeout", "api_key", "engine", "request_timeout"}


@pytest.mark.parametrize("symbol", sorted(REWRITES))
def test_every_read_the_pack_carries_is_a_field_of_the_result_the_call_returns(symbol: str) -> None:
    params = REWRITES[symbol]
    for path in params.result_paths:
        model: type[BaseModel] | None = RESULTS[params.new_call]
        for segment in path.replace("[]", "").split("."):
            assert model is not None, f"{path} reads through a field that is not a model"
            assert segment in model.model_fields, f"{path}: {model.__name__} has no {segment}"
            model = _model(model.model_fields[segment].annotation)


def test_the_dict_reads_fixture_reads_every_listed_path_by_its_keys() -> None:
    """The rewrite rests on `r["a"]` and `r.a` reading one field of a 0.28.1 result; the weekly
    job runs the fixture on 0.28.1 and on the new releases and compares what it prints."""
    fixture = BUNDLED.path.parent / "fixtures" / "positive" / "dict_reads.before.py"
    source = fixture.read_text("utf-8")
    for params in REWRITES.values():
        for path in params.result_paths:
            keys = "".join(
                f'["{part.removesuffix("[]")}"]' + ("[0]" if part.endswith("[]") else "")
                for part in path.split(".")
            )
            assert keys in source, f"no read of {path} by its keys"


def test_a_new_result_is_not_a_dictionary() -> None:
    """Why a string key along a path becomes an attribute, and any other read withholds the file."""
    result = openai.types.Completion.model_validate(
        {
            "id": "cmpl-1",
            "object": "text_completion",
            "created": 1,
            "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop", "text": "hi"}],
        }
    )
    assert result.choices[0].text == "hi"
    with pytest.raises(TypeError):
        result["choices"]  # type: ignore[index]
    assert not hasattr(result, "get")


def test_the_module_settings_the_pack_leaves_alone_are_read_by_the_module_client() -> None:
    """`api_key` and `organization` are module attributes the lazily built client reads."""
    assert {"api_key", "organization"} <= {*dir(openai)}
    assert type(openai.chat).__name__ == "ChatProxy"


@pytest.mark.parametrize(("legacy", "new"), sorted(SETTINGS.items()))
def test_a_renamed_setting_is_read_by_the_module_client_as_written(
    monkeypatch: pytest.MonkeyPatch, legacy: str, new: str
) -> None:
    """The new name exists, the old one does not, and no trailing slash is added to a value."""
    assert hasattr(openai, new)
    assert not hasattr(openai, legacy.rpartition(".")[2])
    for written in ("http://example.invalid/v1", "http://example.invalid/v1/"):
        monkeypatch.setattr(openai, new, written)
        assert str(openai.chat.completions._client.base_url) == written
