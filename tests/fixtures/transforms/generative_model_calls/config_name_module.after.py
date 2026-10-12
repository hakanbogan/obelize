"""A generation config held by a module-level name, read by a model built in a function.

A chat bot in the benchmark passes its four keys by name. The name has one assignment, a mapping
of four legal keys, and the model is its only reader, so the keys can be written into the call
the way an inline mapping is. The name stays where it is: another module may import it, and
nothing about it needs to change.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")

GENERATION_CONFIG = {
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 1024,
}


def reply(text):
    chat = client.chats.create(
        model="gemini-1.5-flash",
        config=types.GenerateContentConfig(
            temperature=0.7,
            top_p=0.95,
            top_k=40,
            max_output_tokens=1024,
        ),
    )
    return chat.send_message(message=text).text
