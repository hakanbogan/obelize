"""A configuration object held by a module-level name, spelled through the module.

`genai.GenerationConfig` is a symbol this rule claims itself, where the spelling through the
`types` submodule is the import rule's. The object stays under its name, as the same keys in the
new SDK's class, and the model that read it gets them in its call.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")

CONFIG = types.GenerateContentConfig(temperature=0.2)


def answer(prompt):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2),
    ).text
