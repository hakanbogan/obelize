"""The embedding result read with `.get`, which the legacy mapping allowed too.

The new call returns an object with no `get`, so the read raises
`AttributeError`. No spelling of the key is what gives it away, which is why
the rule asks whether the result is used at all rather than how it is read.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def embed(sentence):
    response = genai.embed_content(model="models/gemini-embedding-001", content=sentence)
    return response.get("embedding")
