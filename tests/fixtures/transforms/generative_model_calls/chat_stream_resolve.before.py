"""A chat's stream resolved and then read whole.

The chat surface streams through a different method, and what it returns is a
generator in the same way, with no `resolve()` and no `text`.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def converse(text):
    chat = MODEL.start_chat()
    response = chat.send_message(text, stream=True)
    response.resolve()
    return response.text
