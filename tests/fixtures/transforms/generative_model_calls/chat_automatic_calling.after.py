"""A chat that asked for automatic function calling.

Legacy automatic function calling is off by default and the new SDK's is on,
so a chat that asked for it explicitly is not a chat that can be created by
moving the keyword or by dropping it. The same fact refuses `tools=` on the
constructor, one object further back.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def converse(text):
    chat = MODEL.start_chat(enable_automatic_function_calling=True)
    return chat.send_message(text).text
