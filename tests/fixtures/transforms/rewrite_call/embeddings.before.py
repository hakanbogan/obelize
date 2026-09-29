"""The embedding call, and the three keywords that travel inside a config object.

Two calls, because the rewrite has two shapes: one the author already split
across lines, which stays split, and one that fits on its line and keeps it.
Both throw the result away, the one shape this rule writes (CODEMOD-07).
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def embed(sentence):
    genai.embed_content(
        model="models/gemini-embedding-001",
        content=sentence,
        task_type="retrieval_document",
    )


def embed_plain(sentence):
    genai.embed_content(model="models/gemini-embedding-001", content=sentence)
