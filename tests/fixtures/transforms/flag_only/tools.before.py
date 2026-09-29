"""A tool declaration, and the default that flipped underneath it.

`flag_only` is the right kind here because nothing about this is an argument
that moves: automatic function calling is off by default in google-generativeai
and on by default in google-genai, so a declaration carried across unchanged
starts calling the function it describes. The four names below are the whole of
the legacy tools surface that is a name at all -- `tools=` and `tool_config=`
are constructor keywords and resolve to nothing, which is why the pack flags
the classes instead (PACK_SPEC, "The tools surface is named by its types
classes").
"""

import google.generativeai as genai
from google.generativeai.types import (
    CallableFunctionDeclaration,
    FunctionDeclaration,
    FunctionLibrary,
    Tool,
)

genai.configure(api_key="")

WEATHER = FunctionDeclaration(name="weather", description="Weather for one city.")
CLOCK = CallableFunctionDeclaration(name="now", description="The time.", function=len)
LIBRARY = FunctionLibrary(tools=[Tool(function_declarations=[WEATHER, CLOCK])])


def ask(question):
    model = genai.GenerativeModel("gemini-1.5-flash", tools=LIBRARY)
    return model.generate_content(question).text
