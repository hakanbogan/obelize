"""A history entry whose role neither SDK accepts.

`assistant` is the spelling every other chat API uses and the one real code
gets wrong; the new SDK raises `ValueError: Role must be user or model`. The
roles are pack data, so this refusal is a row of a table rather than a name
this rule knows.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def converse(text):
    chat = MODEL.start_chat(history=[{"role": "assistant", "parts": ["hello"]}])
    return chat.send_message(text).text
