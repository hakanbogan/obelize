"""The sharp case: the file this run would write is the one with the hand edit.

This is TM-8 stated literally -- obelize is about to replace bytes somebody
typed and has not committed. The refusal names it, and names it twice: once as
a dirty path and once as a path on the plan.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
