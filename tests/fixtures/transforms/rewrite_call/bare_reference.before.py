"""The embedding function handed around rather than called.

A rule that claimed every finding carrying its symbol would claim this one,
and there is no call at that position to rewrite. The name is what the author
wrote and a rewrite would have to follow it to the place it is used, which is
dataflow a per-file scan does not do -- so nothing claims it, and the file is
one no run writes.

The key beside this file is what the rules produce and not what a run writes:
a finding nothing claims withholds the file exactly as a refusal does.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

EMBEDDERS = {"document": genai.embed_content}


def embed(kind, sentence):
    return EMBEDDERS[kind](model="models/gemini-embedding-001", content=sentence)
