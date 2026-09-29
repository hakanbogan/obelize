"""The same table in a module that already binds `types`, which is the stdlib's.

`from google.genai import types` would shadow it, so the rewrite falls back to
the pack's `types_alias_fallback` and reads every name through that instead.
"""

import types

from google.generativeai.types import HarmBlockThreshold, HarmCategory

HATE = HarmCategory.HARM_CATEGORY_HATE_SPEECH
ONLY_HIGH = HarmBlockThreshold.BLOCK_ONLY_HIGH
STRICT = {HATE: ONLY_HIGH}


def frozen():
    """The stdlib `types`, which is why the fallback exists."""
    return types.MappingProxyType(STRICT)
