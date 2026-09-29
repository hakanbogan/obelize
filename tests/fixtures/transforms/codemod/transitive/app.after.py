"""The file this repository migrates whole.

Nothing in it refuses. What keeps the legacy pin is `retry.py`, which never
names the legacy SDK and imports a distribution only the legacy SDK installs.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def note(diff):
    return client.models.generate_content(model="gemini-1.5-flash", contents=diff).text
