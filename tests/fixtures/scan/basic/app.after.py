"""Summarise release notes with the Gemini API."""

import os

from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  # keep this comment


def summarize(prompt):
    """Return a two-sentence summary of ``prompt``."""
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=f"Summarize the following in exactly two sentences:\n\n{prompt}",
        config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=512),
    )
    return response.text


def count_tokens(prompt):
    return client.models.count_tokens(model="gemini-1.5-flash", contents=prompt).total_tokens
