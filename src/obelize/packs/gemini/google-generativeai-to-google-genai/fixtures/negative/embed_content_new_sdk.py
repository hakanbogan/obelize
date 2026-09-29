"""The embedding call after migration, including the result access."""

from google import genai
from google.genai import types

client = genai.Client()


def embed(sentence):
    response = client.models.embed_content(
        model="models/gemini-embedding-001",
        contents=sentence,
        config=types.EmbedContentConfig(task_type="retrieval_document", title="notes"),
    )
    return response.embeddings[0].values
