"""The file in this repository that a run does write.

Nothing here refuses, so this file migrates exactly as `../clear/app.py` does
-- and the manifest beside it comes out differently, because `refused.py`
does not.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
