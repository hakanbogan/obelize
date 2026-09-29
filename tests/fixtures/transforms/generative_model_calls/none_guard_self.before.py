"""A model on the instance that a method checks before it uses it.

Comparing a model with `None` hands it to nobody, so the scan grades the
binding closed-world (ADR-019 D9). It is still a reference that outlives the
rewrite, and this rule deletes the constructor: the check would read an
attribute nothing assigns any more, and raise `AttributeError`. The rule
refuses the group.
"""

import google.generativeai as genai


class Desk:
    """One model for the whole support desk."""

    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    def answer(self, prompt):
        if self.model is None:
            return ""
        return self.model.generate_content(prompt).text
