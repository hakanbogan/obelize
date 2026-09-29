"""The same dirty tree as `../dirty_worktree/`, with the permission given.

`--allow-dirty` is the one flag that turns the refusal off, so this case is
what proves the refusal is a policy and not an inability. The hand edit in
`notes.py` is still on the disk when the run is over.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
