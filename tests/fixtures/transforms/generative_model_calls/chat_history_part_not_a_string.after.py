"""A part that is neither a string nor the mapping the new SDK wants.

A name could hold a `Part` object, and wrapping one of those produces a
mapping with an object inside it -- so a part is rewritten only when the
author wrote something that is certainly a string.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def converse(text, payload):
    chat = MODEL.start_chat(history=[{"role": "user", "parts": [payload]}])
    return chat.send_message(text).text
