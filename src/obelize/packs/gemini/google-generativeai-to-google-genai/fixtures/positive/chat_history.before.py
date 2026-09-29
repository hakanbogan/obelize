"""Two attribute reads with no counterpart: chat history, and a model field."""

import google.generativeai as genai

genai.configure(api_key="")


class Session:
    def __init__(self):
        self.model = genai.GenerativeModel("gemini-1.5-flash")
        self.chat = self.model.start_chat(history=[])

    def turns(self):
        return len(self.chat.history)

    def last_reply(self):
        return self.chat.last


def methods_of(name):
    return genai.get_model(name).supported_generation_methods
