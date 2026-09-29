"""A model on the instance, with the client placed on the same instance.

The `configure` is in `__init__` and both readers are in other methods, so
the client lands on `self` -- and so the calls this rule writes are spelled
against `self.client` without this rule knowing how that was decided. One of
the two calls is wide enough to wrap and the other is not, which is the width
clause deciding two lines of one class differently.
"""

import google.generativeai as genai


class Desk:
    """One model for the whole support desk."""

    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    def answer(self, prompt):
        return self.model.generate_content(prompt).text

    def size(self, prompt):
        return self.model.count_tokens(prompt).total_tokens
