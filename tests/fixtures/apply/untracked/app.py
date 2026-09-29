"""A committed tree with untracked files beside it, which is not a dirty tree.

`.obelize/latest` is the file obelize writes itself, and counting it would
make every run after the first one refuse to write anything. Neither
untracked file is on the plan, and `../untracked_target/` is one that is.
`../staged/` is the same file after a `git add`, which is dirty.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
