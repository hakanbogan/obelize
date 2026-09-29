"""A model on the instance, with the client placed on the same instance.

The `configure` is in `__init__` and both readers are in other methods, so
the client lands on `self` -- and so the calls this rule writes are spelled
against `self.client` without this rule knowing how that was decided. One of
the two calls is wide enough to wrap and the other is not, which is the width
clause deciding two lines of one class differently.
"""

from google import genai


class Desk:
    """One model for the whole support desk."""

    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)

    def answer(self, prompt):
        return self.client.models.generate_content(model="gemini-1.5-flash", contents=prompt).text

    def size(self, prompt):
        return self.client.models.count_tokens(
            model="gemini-1.5-flash",
            contents=prompt,
        ).total_tokens
