"""The embedding result read the way the legacy mapping allowed.

The legacy call returned a mapping and the new one returns an object, so
`["embedding"]` has two correct rewrites -- `.embeddings[0].values` for a
single content and a comprehension over `.embeddings` for a batch -- and which
one is right depends on the runtime type of `content`. Both spellings of the
read are here: through the name the result was bound to, and on the call
itself.

The key beside this file is what the rules produce and not what a run writes:
one of them refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def embed(sentence):
    response = genai.embed_content(model="models/gemini-embedding-001", content=sentence)
    return response["embedding"]


def embed_inline(sentence):
    return genai.embed_content(model="models/gemini-embedding-001", content=sentence)["embedding"]
