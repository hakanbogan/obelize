"""A conversation written out as the model's input, with bare-string parts.

The legacy SDK took a list of turns whose parts were plain strings, and the new
one validates each part and rejects a string. The list is written here, so it
is reshaped the way a chat history is: each string part is wrapped.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def ask():
    return MODEL.generate_content([{"role": "user", "parts": ["Hi"]}]).text
