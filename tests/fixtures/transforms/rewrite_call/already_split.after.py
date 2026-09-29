"""A call the author split across lines whose rewrite would fit on one.

The layout rule's first clause on its own. Every other split call in this
corpus is also too wide to rejoin, so this is the one file where a rewrite
that ignored what the author wrote would be visible: the trigger only ever
*adds* line breaks, and a call somebody split on purpose stays split.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def embed(text):
    client.models.embed_content(
        model="text-embedding-004",
        contents=text,
    )
