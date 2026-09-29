"""A stream resolved and then read whole, which the legacy response allowed.

`resolve()` walked the rest of the stream and `text` joined it. The new
streaming call returns a generator of chunks, which has neither, so a rewrite
raises `AttributeError` where the legacy code returned the text.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    response = MODEL.generate_content(prompt, stream=True)
    response.resolve()
    return response.text
