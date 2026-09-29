"""Listing and getting a model, the two calls the migration guide omits."""

from google import genai

client = genai.Client(api_key="")


def names():
    return [entry.name for entry in client.models.list()]


def details():
    return client.models.get(model="models/gemini-1.5-flash")
