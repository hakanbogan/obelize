"""A configuration held by a name that belongs to the function that builds the model.

Nothing outside the function can read it, so it goes with the model: once its keys are in the
call there is nothing left for the assignment to do. Both forms the legacy SDK took are here, a
mapping and a `GenerationConfig`, and the second would not survive the import being renamed.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def warm(prompt):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2),
    ).text


def bold(prompt):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.9, top_p=0.8),
    ).text
