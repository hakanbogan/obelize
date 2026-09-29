"""A constructor keyword that becomes a field of the emitted configuration.

There is no configuration object here at all, so the one this rule emits is
invented rather than rebuilt -- which is the case where there is no earlier
layout decision to respect.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def answer(prompt):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction="Answer in one sentence."),
    ).text
