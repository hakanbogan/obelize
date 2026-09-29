"""The repository where nothing migrates, and the empty patch it produces.

Nothing configures a client, so the client source never resolves, every row is
withheld and F-2 leaves the manifest alone: a plan with rows in it and not one
file to write. `patch.diff` is written and is zero bytes long, which is the
honest thing for a diff of no changes to be.
"""

import google.generativeai as genai

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
