"""The task types the legacy SDK took in other spellings.

The legacy call lowered a string and looked it up, so `"document"` and
`"Retrieval_Query"` both worked. The new configuration sends the string as
written, and the service reads the UPPER_SNAKE name, so the rule writes that.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def embed_document(sentence):
    client.models.embed_content(
        model="models/gemini-embedding-001",
        contents=sentence,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
    )


def embed_query(sentence):
    client.models.embed_content(
        model="models/gemini-embedding-001",
        contents=sentence,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
    )
