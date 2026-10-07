"""The same table in a module that already binds `types`, which is the stdlib's.

`from google.genai import types` would shadow it, so the rewrite falls back to
the pack's `alias_fallbacks` and reads every name through that instead.
"""

import types

from google.genai import types as genai_types

HATE = genai_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH
ONLY_HIGH = genai_types.HarmBlockThreshold.BLOCK_ONLY_HIGH
STRICT = {HATE: ONLY_HIGH}


def frozen():
    """The stdlib `types`, which is why the fallback exists."""
    return types.MappingProxyType(STRICT)
