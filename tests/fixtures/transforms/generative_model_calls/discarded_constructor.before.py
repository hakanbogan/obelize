"""A constructor whose result nobody keeps.

There is no binding, so there is no group and nothing to fold the model name
into. That is what `receiver_unresolved` says in as many words, and its own
definition names this case: a constructor result that is never bound.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def warm_up():
    genai.GenerativeModel("gemini-1.5-flash")
