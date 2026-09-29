"""A `types` import the type checker reads, and a call that needs one at runtime.

The configuration becomes `types.GenerateContentConfig(...)`, and the rule
spelled it with the one `types` this file binds -- under `if TYPE_CHECKING:`,
which never runs. The call raised `NameError` (transforms:CODEMOD-04).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google import genai

if TYPE_CHECKING:
    from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config={"temperature": 0.2})


def answer(prompt):
    return MODEL.generate_content(prompt).text
