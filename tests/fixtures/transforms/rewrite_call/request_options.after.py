"""The keyword that every legacy free function took and none of the new ones do.

`request_options=` configured retries and timeouts on the legacy call. The new
SDK carries those on the client rather than on the call, so there is nothing
for this rule to move them into.

The key beside this file is what the rules produce and not what a run writes:
one of them refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def embed(sentence):
    return genai.embed_content(
        model="models/gemini-embedding-001",
        content=sentence,
        request_options={"timeout": 30},
    )
