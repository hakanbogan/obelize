"""A stream walked chunk by chunk, and then read whole.

The loop is the part the new call keeps. The legacy response also joined the
chunks it had seen into `text`; a generator has no such attribute, so the last
line raises once the loop is done.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    response = MODEL.generate_content(prompt, stream=True)
    for chunk in response:
        print(chunk.text, end="")
    return response.text
