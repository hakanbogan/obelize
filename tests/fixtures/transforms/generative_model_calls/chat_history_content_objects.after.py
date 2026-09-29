"""A history whose entries are objects rather than mappings.

The legacy SDK accepted a list of `Content` objects and so does the new one,
but this rule reads a history to reshape its parts and an object is a shape it
cannot see into. Refusing leaves a file that works; carrying it across
unexamined is the pass-through ADR-008 calls the worst outcome available.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

def turn(role, text):
    return {"role": role, "parts": [text]}


MODEL = genai.GenerativeModel("gemini-1.5-flash")


def converse(text):
    chat = MODEL.start_chat(history=[turn("user", "hello")])
    return chat.send_message(text).text
