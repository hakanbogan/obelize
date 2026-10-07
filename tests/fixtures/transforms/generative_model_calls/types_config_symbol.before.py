"""The configuration class reached through the submodule the import rule owns.

`symbol_map` renames that spelling where it stands, so by the time this
rule asks for a name for the submodule the import rule has already bound one
and there is nothing to introduce. This rule still has to recognise the call
as a configuration, or it would refuse a shape it can do -- which is why the
pack names the alias beside the spelling it claims.
"""

import google.generativeai as genai
from google.generativeai.types import GenerationConfig

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config=GenerationConfig(temperature=0.2))


def answer(prompt):
    return MODEL.generate_content(prompt).text
