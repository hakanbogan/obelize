"""The file this repository migrates whole.

What keeps the legacy pin is `analysis.ipynb`, which `include` does not take
and which imports the legacy SDK in a cell.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def note(diff):
    return client.models.generate_content(model="gemini-1.5-flash", contents=diff).text
