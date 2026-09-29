"""A conversation written out as the model's input, with bare-string parts.

The legacy SDK took a list of turns whose parts were plain strings, and the new
one validates each part and rejects a string. The list is written here, so it
is reshaped the way a chat history is: each string part is wrapped.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def ask():
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=[{"role": "user", "parts": [{"text": "Hi"}]}],
    ).text
