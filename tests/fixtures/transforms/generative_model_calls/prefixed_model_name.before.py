"""A model named as a resource rather than as a bare name.

Both SDKs accept it, so it is carried across exactly as written and pointed
at rather than rewritten: a rule that tidied the author's string would be
changing a value it has no evidence about.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("models/gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text
