"""A `configure` that runs only when a key is set.

The legacy call is skipped without a key and the model fails later, at its
first request. The new client would be bound only with a key, and `answer()`
would raise `NameError` without one (transforms:CODEMOD-10).
"""

import os

import google.generativeai as genai

if os.environ.get("GEMINI_API_KEY"):
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text
