"""The file in this repository that a run does write.

Nothing here refuses, so this file migrates exactly as `../clear/app.py` does
-- and the manifest beside it comes out differently, because `refused.py`
does not.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def note(diff):
    return client.models.generate_content(model="gemini-1.5-flash", contents=diff).text
