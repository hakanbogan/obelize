"""The check and the use on one line.

A line that carries a rewritten use is not therefore a line with nothing
else on it: the rule counts the references on it, and this one has two for
one use.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text if MODEL is not None else ""
