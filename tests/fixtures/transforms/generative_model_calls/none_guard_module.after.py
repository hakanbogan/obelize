"""A module-level model that a function checks before it uses it.

The same reference as `none_guard_self`, on a name rather than an attribute:
with the constructor gone, `MODEL is None` raises `NameError`.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    if MODEL is None:
        return ""
    return MODEL.generate_content(prompt).text
