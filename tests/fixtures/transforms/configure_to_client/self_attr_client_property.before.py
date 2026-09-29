"""A property called `client` on the class the client would be put on.

`self.client = ...` on a class whose `client` is a property without a setter
raises `AttributeError` when the instance is built (transforms:CODEMOD-25). A
name the class body defines is taken, and the ladder moves to the fallback.
"""

import google.generativeai as genai


class Assistant:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    @property
    def client(self):
        return "support-desk"

    def answer(self, prompt):
        return self.model.generate_content(prompt).text
