"""A support desk whose model can be swapped, and dropped when it closes.

`switch` puts whatever it is handed where `__init__` put the legacy model,
and `close` puts `None` there. Only one of the three assignments builds a
legacy object, so a detector that counted constructors would call the
attribute closed-world and rewrite `answer` to a call on the client with the
first model's name: a desk switched to another model would go on answering
with the first, and a closed one would go on answering at all.
"""
import google.generativeai as genai


class Desk:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    def answer(self, prompt):
        return self.model.generate_content(prompt).text

    def switch(self, model):
        self.model = model

    def close(self):
        self.model = None
