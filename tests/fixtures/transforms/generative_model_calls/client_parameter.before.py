"""A parameter called `client`, in a function whose model call becomes a client call.

The module's client was named `client` because nothing at module level used
the name. The rewritten call in `answer` then read the parameter instead -- an
HTTP client, whose `.models` raises `AttributeError` (transforms:CODEMOD-02).
A name any scope in the file binds is taken, so the ladder moves on.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt, client=None):
    return MODEL.generate_content(prompt).text
