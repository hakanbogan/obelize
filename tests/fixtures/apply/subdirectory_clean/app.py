"""The repository that reaches a disk whole.

Nothing refuses, the tree is committed and clean, and both files this run
produces are replaced in place. What is graded here that no corpus before it
could grade is the *disk*: every corpus up to T16 compared bytes a driver
returned, and this one compares bytes that survived a temporary file, an
`fsync`, a `chmod` and a rename.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
