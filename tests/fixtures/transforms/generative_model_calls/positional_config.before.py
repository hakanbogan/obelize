"""C-22's own example: three positional arguments, the middle one skipped.

Every legacy constructor parameter is positional-or-keyword and the second is
the safety table, so the third positional is the configuration and a reader
who assumed otherwise would swap two arguments. The edit says the mapping was
made by index so the reader can check it.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", None, {"temperature": 0.2})


def answer(prompt):
    return MODEL.generate_content(prompt).text
