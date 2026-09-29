"""The two reads after migration: a method call, and a field that survived."""

from google import genai

client = genai.Client()


class Session:
    def __init__(self):
        self.chat = client.chats.create(model="gemini-1.5-flash")

    def turns(self):
        return len(self.chat.get_history())


def token_limit(name):
    return client.models.get(model=name).input_token_limit
