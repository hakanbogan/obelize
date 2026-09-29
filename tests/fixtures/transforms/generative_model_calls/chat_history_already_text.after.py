"""A history already written the way the new SDK wants it.

The mapping form of a part is legal in both SDKs, so it passes through as
itself and nothing is reshaped -- which is why this edit carries no warning
and its neighbour does. A part that is neither a string nor that one mapping
is refused rather than wrapped, because a name could hold an object.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def converse(text):
    chat = client.chats.create(
        model="gemini-1.5-flash",
        history=[{"role": "user", "parts": [{"text": "hello"}]}],
    )
    return chat.send_message(message=text).text
