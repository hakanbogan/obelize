"""A configuration on the constructor and another on the call.

The legacy SDK merged the two and let the call win key by key, so the call's
temperature replaces the constructor's in the constructor's position and the
key only the constructor has is kept.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def answer(prompt):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.9, top_p=0.9),
    ).text
