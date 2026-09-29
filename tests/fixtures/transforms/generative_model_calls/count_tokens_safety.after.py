"""A safety table, and a call that counts tokens rather than generating them.

`types.CountTokensConfig` has no safety field, and a safety threshold does not
change how many tokens a prompt is -- so the table is dropped for this call
under the rule that drops the sampling configuration (ADR-010 F-3), and the
edit says so. `system_instruction` is the one that would refuse instead,
because that really does change the count.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def size(prompt):
    return client.models.count_tokens(model="gemini-1.5-flash", contents=prompt).total_tokens
