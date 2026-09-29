"""The only module here, and the rules migrate all of it.

So `survey` reports one migrated file and nothing blocking, which is the state
ADR-010 F-2 calls both halves clear: the legacy declaration stops naming the
legacy distribution instead of gaining a neighbour.
"""

import google.generativeai as genai

genai.configure(api_key="")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
