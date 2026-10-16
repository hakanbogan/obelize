"""What `openai/openai-0-to-1` claims about openai 0.28.1, read from it and compared to a snapshot.

Run by the weekly end-to-end job under `uv run --isolated --no-project --with openai==0.28.1`,
since that release cannot share an environment with the one the unit tests import. Standard
library only, so nothing but the SDK is installed.

    python -I tests/packs/openai_legacy_check.py tests/packs/openai_legacy_surface.json
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import openai

# 0.28.1 defines names the installed stubs do not, so it is read untyped.
sdk: Any = openai


def surface() -> dict[str, object]:
    top = {}
    for name in sorted(name for name in dir(sdk) if not name.startswith("_")):
        value = getattr(sdk, name)
        if inspect.ismodule(value):
            top[name] = "module"
        elif inspect.isclass(value):
            top[name] = "class"
        elif callable(value):
            top[name] = "function"
        else:
            top[name] = "value"
    errors = importlib.import_module("openai.error")
    return {
        "version": sdk.version.VERSION,
        "responses": responses(),
        "top": top,
        "submodules": sorted(module.name for module in pkgutil.iter_modules(sdk.__path__)),
        "error_classes": sorted(
            name
            for name, value in vars(errors).items()
            if inspect.isclass(value) and not name.startswith("_")
        ),
    }


# The statuses answered with the API's own error body; each name is the response the legacy and
# the new side both get, and `test_openai_facts.py` reads the same ones back off the new release.
STATUSES = (400, 401, 403, 404, 415, 429, 500, 503)


class _Server(BaseHTTPRequestHandler):
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
        """Silent: the output is the comparison."""


def responses() -> dict[str, list[str]]:
    """What each response makes `ChatCompletion.create` raise: the classes of `openai.error` the
    exception is, most derived first, and none for an exception that is not one of them."""
    server = HTTPServer(("127.0.0.1", 0), _Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    unbound = socket.socket()
    unbound.bind(("127.0.0.1", 0))
    closed = f"http://127.0.0.1:{unbound.getsockname()[1]}"
    unbound.close()
    # Each case is the base URL, the API key and the keywords of the call.
    cases: dict[str, tuple[str, str | None, dict[str, Any]]] = {
        **{f"status {status}": (f"{url}/status/{status}", "k", {}) for status in STATUSES},
        "empty 200 body": (f"{url}/empty", "k", {}),
        "no API key": (url, None, {}),
        "timeout": (f"{url}/slow", "k", {"request_timeout": 0.3}),
        "connection refused": (closed, "k", {}),
    }
    found = {}
    for name, (base, key, keywords) in cases.items():
        sdk.api_base, sdk.api_key = base, key
        try:
            sdk.ChatCompletion.create(model="m", messages=[], **keywords)
        except Exception as error:
            found[name] = [
                cls.__name__ for cls in type(error).__mro__ if cls.__module__ == "openai.error"
            ]
        else:
            found[name] = []
    server.shutdown()
    return found


def _positional(method: Any, count: int) -> list[str]:
    """The first `count` parameters of a bound method, in declared order."""
    return list(inspect.signature(method).parameters)[:count]


def behaviour() -> list[str]:
    """What the pack's refusals and its one rewrite rest on, as the names of what failed."""
    failed = []
    checks = {
        "results are dictionaries": issubclass(sdk.openai_object.OpenAIObject, dict),
        "create and acreate on the rewritten resources": all(
            inspect.ismethod(getattr(resource, method))
            for resource in (
                sdk.ChatCompletion,
                sdk.Completion,
                sdk.Embedding,
                sdk.Image,
                sdk.Moderation,
            )
            for method in ("create", "acreate")
        ),
        "transcribe and translate on Audio": all(
            inspect.ismethod(getattr(sdk.Audio, method)) for method in ("transcribe", "translate")
        ),
        "acreate is a coroutine function": all(
            inspect.iscoroutinefunction(resource.acreate)
            for resource in (sdk.ChatCompletion, sdk.Completion, sdk.Embedding, sdk.Image)
        ),
        "positional order of the rewritten calls": (
            _positional(sdk.Moderation.create, 1) == ["input"]
            and _positional(sdk.Audio.transcribe, 2) == ["model", "file"]
            and _positional(sdk.Audio.translate, 2) == ["model", "file"]
        ),
        "an image is created from keywords alone": (
            _positional(sdk.Image.create, 1) == ["api_key"]
            and bool(sdk.Image.create.__code__.co_flags & inspect.CO_VARKEYWORDS)
        ),
        "the settings are plain module attributes": all(
            hasattr(sdk, name)
            for name in ("api_key", "organization", "api_base", "api_type", "api_version")
        ),
        "the kept names are defined": all(
            hasattr(sdk, name) for name in ("OpenAIError", "VERSION", "api_key", "organization")
        ),
    }
    for claim, held in checks.items():
        if not held:
            failed.append(claim)
    return failed


def main(path: str) -> int:
    with open(path, encoding="utf-8") as handle:
        expected = json.load(handle)
    found = surface()
    problems = [
        f"{key} differs from the snapshot" for key in expected if found[key] != expected[key]
    ]
    problems += behaviour()
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
