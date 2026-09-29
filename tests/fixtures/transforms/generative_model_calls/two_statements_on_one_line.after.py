"""The constructor shares its line with a statement that is not this rule's.

The unit deleted is the statement and not the line, so what is left of the
line survives -- and the semicolon that used to separate the two goes with
the statement that followed it.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

LABEL = "flash"


def answer(prompt):
    return client.models.generate_content(model="gemini-1.5-flash", contents=prompt).text, LABEL
