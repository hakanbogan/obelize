"""The configuration as a mapping literal, which the legacy SDK did not check.

The unvalidated form is how a key the legacy class never had reached the
server, so every key is checked here against the legal set before any of them
becomes a field of a class that would accept it.
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
