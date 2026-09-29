"""The two model calls, and the file that must not gain a types import.

`list_models` takes nothing and `get_model` takes one argument that is renamed.
No configuration object is emitted anywhere here, so `from google.genai import
types` would be an import this file never uses.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def names():
    return [entry.name for entry in client.models.list()]


def details():
    return client.models.get(model="models/gemini-1.5-flash")
