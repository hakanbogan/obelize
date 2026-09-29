"""The file this repository does write, beside one it must not touch.

ADR-010 F-1 is a promise about a file on somebody's disk, and until this
corpus it had only ever been kept in memory. `refused.py` has to come back off
the disk byte for byte after a run that wrote two other files in the same
directory.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def note(diff):
    return client.models.generate_content(model="gemini-1.5-flash", contents=diff).text
