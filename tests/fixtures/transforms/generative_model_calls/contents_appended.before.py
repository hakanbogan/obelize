"""A conversation built up one turn at a time, and then handed to the model.

The list is a name here and its turns are appended where the rule does not
reshape them, so what the call is given is decided somewhere else.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def ask(question):
    turns = []
    turns.append({"role": "user", "parts": [question]})
    return MODEL.generate_content(turns).text
