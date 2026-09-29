"""An import that never executes, under `if TYPE_CHECKING:`.

The statement is inside an `If` and `ScopeProvider` still puts it in the
module's own scope, so it is not a `local_import` and the two annotations
resolve through it. C-26 is the correction this file is here for.
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
