"""A configuration on the chat's own call, and why the whole merge is restated.

The legacy SDK merged the model's configuration into the call's key by key.
The new SDK does not: `Chat.send_message` **replaces** the configuration the
chat was created with, so a call that overrides one key has to carry all of
them -- and a call that overrides nothing carries nothing, because the chat
still holds what `chats.create` was given.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def converse(text):
    chat = client.chats.create(
        model="gemini-1.5-flash",
        config=types.GenerateContentConfig(temperature=0.2, top_p=0.9),
    )
    return chat.send_message(
        message=text,
        config=types.GenerateContentConfig(temperature=0.9, top_p=0.9),
    ).text
