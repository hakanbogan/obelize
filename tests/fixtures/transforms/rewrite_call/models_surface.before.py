"""The two model calls, and the file that must not gain a types import.

`list_models` takes nothing and `get_model` takes one argument that is renamed.
No configuration object is emitted anywhere here, so `from google.genai import
types` would be an import this file never uses.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def names():
    return [entry.name for entry in genai.list_models()]


def details():
    return genai.get_model("models/gemini-1.5-flash")
