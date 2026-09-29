"""C-56: a handler for an exception the new object no longer raises.

`response.text` raised when there were no parts and now returns `None`, so
this handler still compiles, never runs, and the branch it guarded is gone.
Nothing about the call itself is wrong, which is why the refusal is about what
is done with the answer.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    response = MODEL.generate_content(prompt)
    try:
        return response.text
    except ValueError:
        return ""
