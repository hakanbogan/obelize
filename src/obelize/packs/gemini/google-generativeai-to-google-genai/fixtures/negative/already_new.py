"""Already migrated. The alias is `genai` on both sides, which is the trap."""

import os

from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])


def answer(question):
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=question,
        config=types.GenerateContentConfig(temperature=0.2),
    )
    return response.text
