"""Placement row 3: the `configure` is in a method and the uses are in others.

`chat_async_self/assistant.after.py:13` is this answer, and the fixture that
wrote it calls it "the single largest inference in the answer key". It is an
inference no longer: the client is an attribute because no local in `__init__`
is visible to `answer`.

Every rule this file needs now exists, so the key beside it is the whole of
what `obelize fix --apply` writes. It was the two rules' partial output until
T12, which is why the model constructor is here at all.
"""

import google.generativeai as genai


class Assistant:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    def answer(self, prompt):
        return self.model.generate_content(prompt).text
