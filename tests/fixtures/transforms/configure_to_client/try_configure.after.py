"""A `configure` inside a `try`.

A `configure` that may not run is a client that may not be bound, whatever the
`except` does (transforms:CODEMOD-10).
"""

import os

from google import genai

try:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
except KeyError:
    pass

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text
