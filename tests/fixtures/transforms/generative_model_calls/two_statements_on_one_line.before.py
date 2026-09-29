"""The constructor shares its line with a statement that is not this rule's.

The unit deleted is the statement and not the line, so what is left of the
line survives -- and the semicolon that used to separate the two goes with
the statement that followed it.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash"); LABEL = "flash"


def answer(prompt):
    return MODEL.generate_content(prompt).text, LABEL
