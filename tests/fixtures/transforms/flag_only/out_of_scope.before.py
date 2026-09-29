"""Nine surfaces with no v0 target, in one module.

The new SDK has no protos module at all, and caching, tuning, operations,
answer, permission and the notebook helpers moved to client services whose
arguments are shaped differently. A prefix match is what claims them: the pack
names the `protos` module and the finding names a class inside it. The
distribution names are deliberately absent from this docstring -- spelled in
full, a flagged surface in prose is a flagged surface, which is the one thing
a prefix match cannot tell apart from the real thing.
"""

import google.generativeai as genai
from google.generativeai import caching, protos

genai.configure(api_key="")


def tuned(source):
    return genai.create_tuned_model(source_model=source)


def grounded(question):
    return genai.answer.generate_answer(question)


def running():
    return genai.operations.list(), genai.get_operation("op")


def shared():
    return genai.permission.get("p"), genai.retriever.get_corpus("c"), genai.notebook.command


def schema():
    return protos.Schema(type=protos.Type.STRING), caching.CachedContent.get("c")
