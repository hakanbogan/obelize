"""The configuration as a mapping literal, which the legacy SDK did not check.

The unvalidated form is how a key the legacy class never had reached the
server, so every key is checked here against the legal set before any of them
becomes a field of a class that would accept it.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config={"temperature": 0.2})


def answer(prompt):
    return MODEL.generate_content(prompt).text
