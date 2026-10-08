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
import sys
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
        "top": top,
        "submodules": sorted(module.name for module in pkgutil.iter_modules(sdk.__path__)),
        "error_classes": sorted(
            name
            for name, value in vars(errors).items()
            if inspect.isclass(value) and not name.startswith("_")
        ),
    }


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
