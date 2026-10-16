"""A handler that would catch the exception the new object no longer raises, without naming it.

`except Exception:` catches the `ValueError` that `response.text` raised when
there were no parts, so the branch it guarded is gone once the attribute returns
`None`. Nothing says the handler was not written for that, so the call is refused
like one that names the error.

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
    except Exception:
        return ""
