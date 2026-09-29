"""A history this rule cannot read, because it is a name.

The parts of every entry have to be reshaped, so the shape has to be visible.
A name is a value this rule would have to run the program to know, and an
unrewritten history imports cleanly and raises `ValidationError` at the first
message.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

OPENING = [{"role": "user", "parts": ["hello"]}]

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def converse(text):
    chat = MODEL.start_chat(history=OPENING)
    return chat.send_message(text).text
