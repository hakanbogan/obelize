"""A history already written the way the new SDK wants it.

The mapping form of a part is legal in both SDKs, so it passes through as
itself and nothing is reshaped -- which is why this edit carries no warning
and its neighbour does. A part that is neither a string nor that one mapping
is refused rather than wrapped, because a name could hold an object.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def converse(text):
    chat = MODEL.start_chat(history=[{"role": "user", "parts": [{"text": "hello"}]}])
    return chat.send_message(text).text
