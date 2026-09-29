"""Placement row 3: the `configure` is in a method and the uses are in others.

`chat_async_self/assistant.after.py:13` is this answer, and the fixture that
wrote it calls it "the single largest inference in the answer key". It is an
inference no longer: the client is an attribute because no local in `__init__`
is visible to `answer`.

Every rule this file needs now exists, so the key beside it is the whole of
what `obelize fix --apply` writes. It was the two rules' partial output until
T12, which is why the model constructor is here at all.
"""

from google import genai


class Assistant:
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)

    def answer(self, prompt):
        return self.client.models.generate_content(model="gemini-1.5-flash", contents=prompt).text
