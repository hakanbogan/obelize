"""A module that already binds the submodule's own name, but not the fallback.

The pack offers two names for the submodule the configuration class lives in.
This file has taken the first, so the second is used -- and the emitted
configuration is spelled against it, because the name a rule writes is the
name the import manager handed back and not the one the pack prefers.
"""

from google import genai
from google.genai import types as genai_types

types = ("flash", "pro")

client = genai.Client(api_key="AIzaNotARealKey")


def answer(prompt):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=genai_types.GenerateContentConfig(temperature=0.2),
    ).text, types
