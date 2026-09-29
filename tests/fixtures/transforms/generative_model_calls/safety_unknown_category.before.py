"""A category the legacy lookup raised `KeyError` for.

`DANGEROUS_CONTENT` is the plausible-looking spelling that was never a legacy
key -- `HARM_CATEGORY_DANGEROUS_CONTENT`, `dangerous` and `danger` are, and
that one is not. Code using it was already broken, so there is nothing to
carry across, and the schema refuses a pack that lists it at all.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash", safety_settings={"DANGEROUS_CONTENT": "block_none"}
)


def answer(prompt):
    return MODEL.generate_content(prompt).text
