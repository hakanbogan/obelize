"""The file this repository migrates whole.

Nothing in it refuses. What keeps the legacy pin is `retry.py`, which never
names the legacy SDK and imports a distribution only the legacy SDK installs.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
