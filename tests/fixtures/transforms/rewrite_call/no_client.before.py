"""A module that embeds and never configures, so there is no client to call.

The scan grades this row eligible and it is right to: `client_source_unresolved`
is a rung-4 code about a module's `configure`, and the projection does not say
that a free function's rewrite is routed through the client either. The rule is
where the missing client is seen, and it raises the code the planner would have
rather than a second name for one defect.

The key beside this file is what the rules produce and not what a run writes:
one of them refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

import google.generativeai as genai


def embed(sentence):
    return genai.embed_content(model="models/gemini-embedding-001", content=sentence)
