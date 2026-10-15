"""The standard library's `types`, imported on the legacy module's own line.

The line is replaced, but `types` on it is not: it stays bound, so the submodule
import takes the pack's fallback instead of shadowing it.
"""

import types, google.generativeai as genai

STRICT = {genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH}
FROZEN = types.MappingProxyType({})
