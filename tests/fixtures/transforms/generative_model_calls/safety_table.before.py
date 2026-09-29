"""The safety table, at every rung the legacy lookup had.

The legacy SDK lower-cased whatever it was handed and looked it up in a closed
dictionary, so `HARM_CATEGORY_HARASSMENT`, `Hate`, `sex` and `danger` are four
spellings of four categories and `BLOCK_NONE`, `low`, `MED` and `high` are four
spellings of four thresholds. Every one of the eight is a row of the pack's
tables; a ninth is refused next door.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash",
    safety_settings={
        "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
        "Hate": "low",
        "sex": "MED",
        "danger": "high",
    },
)


def answer(prompt):
    return MODEL.generate_content(prompt).text
