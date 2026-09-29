"""The tree carries an uncommitted change to a file this run would not touch.

TM-8 is refused over the whole tree and not over the plan. `notes.py` is not
on the plan and is not even scanned, and the apply is still refused: what
`--apply` on a clean tree buys a reviewer is a `git diff` that is the
migration and nothing else, which a change anywhere destroys.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
