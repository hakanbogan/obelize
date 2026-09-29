"""A base class in the same module that already keeps a `self.client`.

Row 3 checked only the attributes the class itself uses on the receiver, so it
chose `self.client` and overwrote the base's HTTP session
(transforms:CODEMOD-25). A base defined in this module is read too, and the
ladder moves to the fallback name.
"""

import requests

from google import genai


class Service:
    def __init__(self):
        self.client = requests.Session()


class Assistant(Service):
    def __init__(self, api_key):
        super().__init__()
        self.genai_client = genai.Client(api_key=api_key)

    def answer(self, prompt):
        return self.genai_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
        ).text
