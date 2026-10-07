"""The configuration class reached through the submodule the import rule owns.

`symbol_map` renames that spelling where it stands, so by the time this
rule asks for a name for the submodule the import rule has already bound one
and there is nothing to introduce. This rule still has to recognise the call
as a configuration, or it would refuse a shape it can do -- which is why the
pack names the alias beside the spelling it claims.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def answer(prompt):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2),
    ).text
