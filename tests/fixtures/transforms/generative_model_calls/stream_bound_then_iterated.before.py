"""A stream bound to a name, and walked by a loop and by nothing else.

The one shape besides a loop's header that the new call keeps: every read of
the name is the iterable of a `for`.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def chunks(prompt):
    stream = MODEL.generate_content(prompt, stream=True)
    for chunk in stream:
        yield chunk.text
