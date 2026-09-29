"""A constructor keyword that becomes a field of the emitted configuration.

There is no configuration object here at all, so the one this rule emits is
invented rather than rebuilt -- which is the case where there is no earlier
layout decision to respect.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash", system_instruction="Answer in one sentence."
)


def answer(prompt):
    return MODEL.generate_content(prompt).text
