"""Listing and getting a model after migration."""

from google import genai

client = genai.Client()


def names():
    return [entry.name for entry in client.models.list()]


def details():
    return client.models.get(model="models/gemini-1.5-flash")
