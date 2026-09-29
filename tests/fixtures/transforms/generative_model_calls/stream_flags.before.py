"""The streaming flag, in both of the two spellings a literal can have.

`True` sends the call to a differently named method; `False` is the legacy
default written out, so the keyword goes and the call does not move. Anything
that is not one of the two is refused next door.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def chunks(prompt):
    for chunk in MODEL.generate_content(prompt, stream=True):
        yield chunk.text


def whole(prompt):
    return MODEL.generate_content(prompt, stream=False).text
