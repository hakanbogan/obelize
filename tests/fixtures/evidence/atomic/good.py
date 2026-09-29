"""The file this repository does migrate, beside one no rule may touch.

It is here so that the run has both halves at once: an edit that lands and a
file whose rows the report has to show with no edit against them.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
