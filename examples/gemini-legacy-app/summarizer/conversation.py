"""A short follow-up conversation about a summary we just produced."""

import google.generativeai as genai

from . import config


class FollowUp:
    """Wraps one chat session. Not thread safe; one per CLI invocation."""

    def __init__(self, summary):
        self.summary = summary
        self.model = genai.GenerativeModel(config.MODEL_NAME)
        self.chat = self.model.start_chat(
            history=[
                {"role": "user", "parts": ["You are reviewing a summary I wrote."]},
                {"role": "model", "parts": ["Understood. Ask away."]},
            ]
        )

    def ask(self, question):
        message = "{}\n\nQuestion: {}".format(self.summary, question)
        response = self.chat.send_message(message)
        return response.text.strip()

    def turns(self):
        """How many messages are on the record, priming included."""
        return len(self.chat.history)
