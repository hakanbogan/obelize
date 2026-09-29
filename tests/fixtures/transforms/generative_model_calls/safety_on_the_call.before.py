"""A safety table on the constructor and another on the call.

The legacy SDK merged the two **by category** -- `merged_ss.update(...)` over a
mapping keyed by category, read off the installed 0.8.6 -- so the call's
threshold replaces the constructor's for the category they share, in the
constructor's position, and the category only the call names is appended.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash",
    safety_settings={"harassment": "block_none", "hate": "block_none"},
)


def answer(prompt):
    return MODEL.generate_content(
        prompt, safety_settings={"hate": "block_only_high", "danger": "block_low_and_above"}
    ).text
