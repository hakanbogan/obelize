"""Placement row 4: the `configure` is in one function and the uses are in another.

A local in `setup()` is not visible in `answer()`, `setup()` is not a method so
there is no attribute to hang the client on, and a module-level client would
move the author's setup out of the function they wrote it in. None of the three
placements dominates, so the rule refuses rather than choosing one.

No run writes this file: the key beside it shows the import moved, because the
other rule succeeded, and F-1 withholds the whole file because this one did not.
"""

import os

from google import genai


def setup():
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])


def answer(prompt):
    model = genai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(prompt).text
