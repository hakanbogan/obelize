"""A base class in the same module that already keeps a `self.client`.

Row 3 checked only the attributes the class itself uses on the receiver, so it
chose `self.client` and overwrote the base's HTTP session
(transforms:CODEMOD-25). A base defined in this module is read too, and the
ladder moves to the fallback name.
"""

import requests

import google.generativeai as genai


class Service:
    def __init__(self):
        self.client = requests.Session()


class Assistant(Service):
    def __init__(self, api_key):
        super().__init__()
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    def answer(self, prompt):
        return self.model.generate_content(prompt).text
