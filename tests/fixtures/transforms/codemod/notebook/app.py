"""The file this repository migrates whole.

What keeps the legacy pin is `analysis.ipynb`, which `include` does not take
and which imports the legacy SDK in a cell.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
