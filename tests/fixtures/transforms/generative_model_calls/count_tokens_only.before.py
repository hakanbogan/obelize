"""A configuration that reaches no call at all, because the only call drops it.

The new token count takes no configuration, so the constructor's is dropped
and the edit says so -- and nothing in the rewritten file mentions the `types`
submodule, so no import of it is written. A rule that decided which imports it
needs before deciding which arguments survive would leave an unused line here.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config={"temperature": 0.2})


def size(prompt):
    return MODEL.count_tokens(prompt).total_tokens
