"""Streaming on the chat, which is a different method rather than a keyword.

The same literal-flag rule as the model's own streaming call, one object
further along: `True` sends the call to a differently named method of the
chat and the keyword goes.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def converse(text):
    chat = MODEL.start_chat()
    for chunk in chat.send_message(text, stream=True):
        yield chunk.text
