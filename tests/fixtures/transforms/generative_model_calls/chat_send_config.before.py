"""A configuration on the chat's own call, and why the whole merge is restated.

The legacy SDK merged the model's configuration into the call's key by key.
The new SDK does not: `Chat.send_message` **replaces** the configuration the
chat was created with, so a call that overrides one key has to carry all of
them -- and a call that overrides nothing carries nothing, because the chat
still holds what `chats.create` was given.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash", generation_config={"temperature": 0.2, "top_p": 0.9}
)


def converse(text):
    chat = MODEL.start_chat()
    return chat.send_message(text, generation_config={"temperature": 0.9}).text
