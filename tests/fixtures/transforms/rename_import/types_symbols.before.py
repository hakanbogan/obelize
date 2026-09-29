"""Configuration helpers and a safety table, reached through the legacy `types`.

Nothing here needs a client and nothing here is a call the new SDK routes
through one, so `rename_import` migrates this file on its own: the import moves
and every name it bound is read through the submodule instead.
"""

from __future__ import annotations

from google.generativeai.types import GenerationConfig, HarmBlockThreshold, HarmCategory

STRICT = {HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH}


def merge(base: GenerationConfig, **overrides: float) -> dict:
    """A bare-name annotation, deferred by `from __future__ import annotations`."""
    return {**dict(base), **overrides}


def strictest(configs: list) -> "GenerationConfig":
    """A string annotation, which resolves the same way."""
    return min(configs, key=lambda config: config.temperature)
