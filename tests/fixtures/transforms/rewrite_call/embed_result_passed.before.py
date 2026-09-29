"""The embedding result handed to another function, which reads it elsewhere.

Nothing in this file reads the result, and the rewrite still changes what the
store receives: an object where it was given a mapping.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def index(store, sentence):
    store.add(genai.embed_content(model="models/gemini-embedding-001", content=sentence))
