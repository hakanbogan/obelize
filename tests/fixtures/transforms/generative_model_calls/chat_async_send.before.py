"""A chat read through a method the pack declares and does not rewrite.

The async chat hangs off a different service of the client than the one a
`start_chat` becomes, so a file that mixes the two cannot be written one call
at a time: `chats.create` would hand back an object this call cannot be made
on. The closure is atomic, so the model's own calls are refused with it.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


async def converse(text):
    chat = MODEL.start_chat()
    return (await chat.send_message_async(text)).text
