"""A free function's rewrite in another method, and the client on the instance.

With nothing but `embed_content` reading the client, the placement table saw no
reader at all, called every reader "in this scope" because there were none,
and made the client a local of `__init__` that `embed` cannot see
(critic:NEW-01). Counted as a reader, it puts this `configure` in row 3.
"""

import google.generativeai as genai

MODEL_NAME = "models/text-embedding-004"


class Index:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)

    def embed(self, text):
        genai.embed_content(model=MODEL_NAME, content=text)
