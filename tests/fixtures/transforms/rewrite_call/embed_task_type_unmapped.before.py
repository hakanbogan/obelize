"""A task type the rule cannot show the new call reads the way the legacy one did.

The legacy lookup took a string it knew, an integer or an enum member, and
raised `KeyError` for the rest. The new configuration sends whatever it is
given, so a name, an integer or a string outside the table is refused rather
than passed on.

The key beside this file is what the rules produce and not what a run writes:
one of them refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def embed(sentence, task):
    return genai.embed_content(
        model="models/gemini-embedding-001",
        content=sentence,
        task_type=task,
    )
