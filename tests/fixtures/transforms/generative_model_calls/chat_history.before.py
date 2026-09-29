"""A literal chat history, and the one argument whose value is rewritten.

The legacy SDK accepted a bare string part and the new one validates the same
mapping with pydantic and rejects it, so each string becomes `{"text": ...}`
and the list keeps its own layout. The edit carries a warning because it
reshapes a data literal the SDK never validated statically. The message
keyword is renamed in the same call: legacy `send_message(content=)` is a
`TypeError` after migration.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", system_instruction="Be terse.")


def converse(text, name):
    chat = MODEL.start_chat(
        history=[
            {"role": "user", "parts": ["hello"]},
            {"role": "model", "parts": [f"Hello, {name}."]},
        ],
    )
    return chat.send_message(content=text).text
