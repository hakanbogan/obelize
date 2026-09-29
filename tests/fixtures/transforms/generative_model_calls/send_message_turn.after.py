"""A chat message written as a turn, which the new chat does not take at all.

`ChatSession.send_message` took a `{"role": ..., "parts": [...]}` mapping. The
new `Chat.send_message` takes parts and nothing shaped like a turn.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def converse(text):
    chat = MODEL.start_chat()
    return chat.send_message({"role": "user", "parts": [text]}).text
