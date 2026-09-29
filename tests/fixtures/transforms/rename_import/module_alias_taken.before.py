"""This repository has a package of its own called `genai`, so the name is taken.

The un-aliased import below binds no name the rewrite can keep, so it has to
introduce one, and the only name this pack may introduce for the module is the
one the repository already uses.
"""

import genai

import google.generativeai

google.generativeai.configure(api_key=genai.API_KEY)


def digest(text):
    model = google.generativeai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(text).text
