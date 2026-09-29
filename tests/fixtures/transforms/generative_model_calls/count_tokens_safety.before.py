"""A safety table, and a call that counts tokens rather than generating them.

`types.CountTokensConfig` has no safety field, and a safety threshold does not
change how many tokens a prompt is -- so the table is dropped for this call
under the rule that drops the sampling configuration (ADR-010 F-3), and the
edit says so. `system_instruction` is the one that would refuse instead,
because that really does change the count.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash", safety_settings={"harassment": "block_none"}
)


def size(prompt):
    return MODEL.count_tokens(prompt).total_tokens
