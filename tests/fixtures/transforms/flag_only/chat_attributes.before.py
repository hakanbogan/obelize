"""Two reads on a chat this module builds, and neither survives the move.

`history` became a method and `last` has no counterpart at all, so both are
`attribute_removed` -- `unsupported` rather than `needs_review`, because there
is nothing for a reviewer to choose between.
"""

import google.generativeai as genai

genai.configure(api_key="")


class Assistant:
    def __init__(self):
        self.model = genai.GenerativeModel("gemini-1.5-flash")
        self.chat = self.model.start_chat()

    def transcript(self):
        return self.chat.history

    def latest(self):
        return self.chat.last
