"""The easy migration reduced to what this rule owns.

A module-level model constant with an inline configuration, read by one call
that generates content and one that counts tokens. The token count cannot
carry the configuration, so that edit says so and the group stays automatic.
"""

import os

from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def summarize(prompt):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=512),
    ).text


def size(prompt):
    return client.models.count_tokens(model="gemini-1.5-flash", contents=prompt).total_tokens
