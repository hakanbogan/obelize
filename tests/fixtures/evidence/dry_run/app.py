"""The repository a dry run writes a plan for and does not touch.

Everything here migrates, so `plan.json` is full, `patch.diff` has something
in it, and `file_edits` is empty -- which is the whole difference between a
plan and an apply, stated by two lists rather than by a flag.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
