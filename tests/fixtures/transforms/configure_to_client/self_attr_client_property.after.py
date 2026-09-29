"""A property called `client` on the class the client would be put on.

`self.client = ...` on a class whose `client` is a property without a setter
raises `AttributeError` when the instance is built (transforms:CODEMOD-25). A
name the class body defines is taken, and the ladder moves to the fallback.
"""

from google import genai


class Assistant:
    def __init__(self, api_key):
        self.genai_client = genai.Client(api_key=api_key)

    @property
    def client(self):
        return "support-desk"

    def answer(self, prompt):
        return self.genai_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
        ).text
