"""C-35: a constructor setting that really does change a token count.

The new count takes no configuration, so the constructor's is dropped and the
edit normally says so. A system instruction is part of what is counted, so
dropping it would change the number and the group is refused instead.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash", system_instruction="Answer in one sentence."
)


def size(prompt):
    return MODEL.count_tokens(prompt).total_tokens
