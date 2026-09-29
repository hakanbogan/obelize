"""Configuration helpers, annotated with a type the SDK only provides for typing.

The import sits under `if TYPE_CHECKING:` and is never executed, and libcst
resolves both annotation forms through it anyway.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.generativeai.types import GenerationConfig

FALLBACK = "GenerationConfig"


def merge(base: GenerationConfig, **overrides: float) -> dict:
    """A bare-name annotation, deferred by `from __future__ import annotations`."""
    return {**dict(base), **overrides}


def strictest(configs: list) -> "GenerationConfig":
    """A string annotation, which resolves the same way."""
    return min(configs, key=lambda config: config.temperature)
