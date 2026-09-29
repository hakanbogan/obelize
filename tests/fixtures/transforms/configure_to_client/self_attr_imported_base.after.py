"""A base class from another module, whose attributes nobody here can see.

Whether `Service` keeps a `self.client` is written in `myapp/service.py`, which
this rule does not read. Neither name can be shown free, so the ladder has no
rung left (transforms:CODEMOD-25).
"""

from google import genai
from myapp.service import Service


class Assistant(Service):
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    def answer(self, prompt):
        return self.model.generate_content(prompt).text
