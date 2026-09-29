"""A configuration that reaches no call at all, because the only call drops it.

The new token count takes no configuration, so the constructor's is dropped
and the edit says so -- and nothing in the rewritten file mentions the `types`
submodule, so no import of it is written. A rule that decided which imports it
needs before deciding which arguments survive would leave an unused line here.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def size(prompt):
    return client.models.count_tokens(model="gemini-1.5-flash", contents=prompt).total_tokens
