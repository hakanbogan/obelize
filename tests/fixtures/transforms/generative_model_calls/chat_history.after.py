"""A literal chat history, and the one argument whose value is rewritten.

The legacy SDK accepted a bare string part and the new one validates the same
mapping with pydantic and rejects it, so each string becomes `{"text": ...}`
and the list keeps its own layout. The edit carries a warning because it
reshapes a data literal the SDK never validated statically. The message
keyword is renamed in the same call: legacy `send_message(content=)` is a
`TypeError` after migration.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def converse(text, name):
    chat = client.chats.create(
        model="gemini-1.5-flash",
        history=[
            {"role": "user", "parts": [{"text": "hello"}]},
            {"role": "model", "parts": [{"text": f"Hello, {name}."}]},
        ],
        config=types.GenerateContentConfig(system_instruction="Be terse."),
    )
    return chat.send_message(message=text).text
