"""Both names the submodule import may bind are already bound in this module.

`types` is the stdlib's and `genai_types` is this project's own helper, so there
is no name left to introduce and the import is withheld.
"""

import types

from google.generativeai.types import HarmBlockThreshold, HarmCategory
from myapp import genai_types

HATE = HarmCategory.HARM_CATEGORY_HATE_SPEECH
ONLY_HIGH = HarmBlockThreshold.BLOCK_ONLY_HIGH


def frozen():
    return types.MappingProxyType(genai_types.normalise({HATE: ONLY_HIGH}))
