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
import socket
import threading
import time
import typing
from http.server import BaseHTTPRequestHandler, HTTPServer
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
RENAMED = {
    symbol: new
    for change in PACK.changes
    if isinstance(change, schema.RenameSymbolChange)
    for symbol, new in change.params.symbols.items()
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
    assert version("openai") in PACK.to.versions()


def test_the_python_the_pack_requires_covers_what_the_installed_release_declares() -> None:
    """The floor release decides it: a later one may need more, and the pack must not need less."""
    requires = metadata("openai")["Requires-Python"]
    pythons = [Version(f"3.{minor}") for minor in range(30)]
    needed = {python for python in pythons if python in SpecifierSet(PACK.to.pythons())}
    declared = {python for python in pythons if python in SpecifierSet(requires)}
    assert declared <= needed
    if Version(version("openai")) == bounds(PACK.to.versions())[0]:
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


@pytest.mark.parametrize("symbol", PACK.from_.since)
def test_a_name_that_proves_a_legacy_release_is_defined_by_it_and_is_a_stub_on_the_new_ones(
    symbol: str,
) -> None:
    """`from.since` says no release below 0.27.0 defines the name (`SOURCES.md`) and that the new
    releases dropped it; the first half is a measurement of past releases, the second is checked."""
    name = symbol.removeprefix("openai.")
    assert SNAPSHOT["top"][name] == "class"
    assert type(getattr(openai, name)).__name__ == "APIRemovedInV1Proxy"


@pytest.mark.parametrize("symbol", PACK.to.introduces)
def test_a_name_the_new_side_introduces_is_defined_by_it_and_was_not_by_the_old_release(
    symbol: str,
) -> None:
    """`to.introduces` says no release of 0.27.0 to 0.28.1 defines the name (`SOURCES.md`): code
    that uses one cannot run on a pin that admits only those."""
    name = symbol.removeprefix("openai.")
    assert name not in SNAPSHOT["top"]
    assert inspect.isclass(getattr(openai, name))


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
    legacy = {*params.positional_to_kw, *params.keywords}
    unknown = sorted({params.arg_map.get(name, name) for name in legacy} - set(parameters))
    assert unknown == [], f"{params.new_call} takes none of {unknown}"
    assert not legacy & {"stream", "timeout", "api_key", "engine"}


def test_engine_and_request_timeout_are_carried_by_the_three_calls_that_read_them() -> None:
    """The legacy half is `openai_legacy_check.py`: those three resources read both themselves."""
    engines = {
        "openai.ChatCompletion.create",
        "openai.Completion.create",
        "openai.Embedding.create",
    }
    for symbol, params in REWRITES.items():
        assert (params.aliases == {"engine": "model"}) == (symbol in engines), symbol
        assert (params.arg_map == {"request_timeout": "timeout"}) == (symbol in engines), symbol
        assert (params.positive_numbers == ("request_timeout",)) == (symbol in engines), symbol


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


def test_a_field_the_server_left_out_or_sent_null_is_none_through_getattr() -> None:
    """Why `r.get("usage")` is written `getattr(r, "usage", None)`: 0.28.1's `.get` gave None too.

    The client builds a result without validating it, so a required field may be missing as well.
    """
    sent_null = openai.types.chat.ChatCompletion.construct(created=1, usage=None)
    left_out = openai.types.chat.ChatCompletion.construct(created=1)
    for result in (sent_null, left_out):
        assert getattr(result, "usage", None) is None
        assert getattr(result, "id", None) is None
        assert getattr(result, "created", None) == 1


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


class _Server(BaseHTTPRequestHandler):
    """The legacy check's server: an API error under the status in the path, or an odd answer."""

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        kind, _, rest = self.path[1:].partition("/")
        if kind == "slow":
            time.sleep(1.5)
        status = int(rest.partition("/")[0]) if kind == "status" else 200
        body = {"error": {"message": "m", "type": "t", "param": None, "code": "c"}}
        data = b"" if kind == "empty" else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        """Silent."""


@pytest.fixture(scope="module")
def raised() -> dict[str, BaseException | None]:
    """What the new release raises for each response the legacy snapshot recorded."""
    server = HTTPServer(("127.0.0.1", 0), _Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    unbound = socket.socket()
    unbound.bind(("127.0.0.1", 0))
    closed = f"http://127.0.0.1:{unbound.getsockname()[1]}"
    unbound.close()
    # The base URL, the API key and the timeout of each case, by the snapshot's names.
    cases: dict[str, tuple[str, str | None, float | None]] = {
        **{
            name: (f"{url}/{name.replace(' ', '/')}/", "k", None)
            for name in SNAPSHOT["responses"]
            if name.startswith("status ")
        },
        "empty 200 body": (f"{url}/empty/", "k", None),
        "no API key": (f"{url}/", None, None),
        "timeout": (f"{url}/slow/", "k", 0.3),
        "connection refused": (f"{closed}/", "k", None),
    }
    found: dict[str, BaseException | None] = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("OPENAI_API_KEY", raising=False)
        for name, (base, key, timeout) in cases.items():
            try:
                openai.OpenAI(
                    api_key=key, base_url=base, max_retries=0, timeout=timeout
                ).chat.completions.create(model="m", messages=[])
            except Exception as error:
                found[name] = error
            else:
                found[name] = None
    server.shutdown()
    return found


def _caught(raised: dict[str, BaseException | None], cls: type[BaseException]) -> set[str]:
    """The responses a handler for `cls` catches on the new release."""
    return {name for name, error in raised.items() if isinstance(error, cls)}


def _raised_by_the_old(name: str) -> set[str]:
    """The responses 0.28.1 raised `openai.error.<name>` or a class derived from it for."""
    return {case for case, classes in SNAPSHOT["responses"].items() if name in classes}


def test_the_snapshot_holds_the_responses_the_new_release_is_asked() -> None:
    assert sorted(SNAPSHOT["responses"]) == sorted(
        [
            *(f"status {status}" for status in (400, 401, 403, 404, 415, 429, 500, 503)),
            "connection refused",
            "empty 200 body",
            "no API key",
            "timeout",
        ]
    )


def test_the_old_classes_were_siblings_under_openai_error() -> None:
    """So none was a base of another, which the new classes' bases are measured against."""
    assert all(classes[1:] == ["OpenAIError"] for classes in SNAPSHOT["responses"].values())


@pytest.mark.parametrize(("legacy", "new"), sorted(RENAMED.items()))
def test_a_renamed_class_is_defined_by_the_new_release_and_the_old_module_is_not(
    legacy: str, new: str
) -> None:
    assert issubclass(getattr(openai, new), openai.OpenAIError)
    assert not hasattr(openai, legacy.split(".")[1])


@pytest.mark.parametrize(("legacy", "new"), sorted(RENAMED.items()))
def test_a_renamed_class_is_raised_for_exactly_the_responses_the_old_one_was(
    raised: dict[str, BaseException | None], legacy: str, new: str
) -> None:
    """A handler for the old class ran for a set of responses; the new one runs for the same."""
    old = _raised_by_the_old(legacy.rpartition(".")[2])
    assert old
    assert _caught(raised, getattr(openai, new)) == old


@pytest.mark.parametrize(
    "name",
    sorted(
        symbol.rpartition(".")[2]
        for symbol in FLAGGED
        if symbol.startswith("openai.error.") and _raised_by_the_old(symbol.rpartition(".")[2])
    ),
)
def test_no_class_of_the_new_release_is_raised_for_exactly_the_responses_a_flagged_one_was(
    raised: dict[str, BaseException | None], name: str
) -> None:
    """Why each is flagged: a rename would catch more or fewer responses than the old class did."""
    old = _raised_by_the_old(name)
    same = [
        cls.__name__
        for cls in list(vars(openai).values())
        if inspect.isclass(cls) and issubclass(cls, Exception) and _caught(raised, cls) == old
    ]
    assert same == []


@pytest.mark.parametrize(
    "change",
    [change for change in PACK.changes if isinstance(change, schema.RenameSymbolChange)],
    ids=lambda change: change.id,
)
def test_the_bases_a_renamed_class_gained_are_the_ones_the_pack_lists(
    change: schema.RenameSymbolChange,
) -> None:
    """The old classes derived from `OpenAIError` alone; every other base is new to a handler."""
    gained = {
        f"openai.{base.__name__}"
        for new in change.params.symbols.values()
        for base in getattr(openai, new).__mro__
        if base.__module__.startswith("openai")
        and base not in {getattr(openai, new), openai.OpenAIError}
    }
    assert gained == set(change.params.now_caught_by)
