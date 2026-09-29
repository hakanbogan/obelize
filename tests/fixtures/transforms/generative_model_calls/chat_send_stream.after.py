"""Streaming on the chat, which is a different method rather than a keyword.

The same literal-flag rule as the model's own streaming call, one object
further along: `True` sends the call to a differently named method of the
chat and the keyword goes.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def converse(text):
    chat = client.chats.create(model="gemini-1.5-flash")
    for chunk in chat.send_message_stream(message=text):
        yield chunk.text
