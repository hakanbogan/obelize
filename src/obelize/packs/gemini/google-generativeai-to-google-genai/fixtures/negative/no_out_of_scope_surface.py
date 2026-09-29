"""The new SDK's own equivalents, which are services rather than classmethods."""

from google import genai
from google.genai import types

client = genai.Client()


def cached(contents):
    return client.caches.create(
        model="gemini-1.5-flash", config=types.CreateCachedContentConfig(contents=contents)
    )


def schema():
    return types.Schema(type="STRING")
