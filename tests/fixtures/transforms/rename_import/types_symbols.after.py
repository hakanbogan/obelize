"""Configuration helpers and a safety table, reached through the legacy `types`.

Nothing here needs a client and nothing here is a call the new SDK routes
through one, so `rename_import` migrates this file on its own: the import moves
and every name it bound is read through the submodule instead.
"""

from __future__ import annotations

from google.genai import types

STRICT = {types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: types.HarmBlockThreshold.BLOCK_ONLY_HIGH}


def merge(base: types.GenerateContentConfig, **overrides: float) -> dict:
    """A bare-name annotation, deferred by `from __future__ import annotations`."""
    return {**dict(base), **overrides}


def strictest(configs: list) -> "types.GenerateContentConfig":
    """A string annotation, which resolves the same way."""
    return min(configs, key=lambda config: config.temperature)
