"""A module that runs on the `configure` in `config.py`.

It has none of its own, so every call here is `client_source_unresolved` and
the file stays on the legacy SDK -- which is what makes `config.py`'s call one
this module still needs.
"""

import google.generativeai as genai

import config

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text
