"""A symbol imported off the legacy module itself, which moved to no module.

`GenerativeModel` has no counterpart anywhere under `google.genai`: the object
became a service on the client, so there is no import for this rule to write.
"""

import os

from google.generativeai import GenerativeModel, configure

configure(api_key=os.environ["GEMINI_API_KEY"])

DEFAULT = GenerativeModel("gemini-1.5-flash")


def draft(question):
    return DEFAULT.generate_content(question).text
