"""Both embedding calls, their results handed back to whoever called.

Nothing here reads the result. The caller does, and it was given a mapping; the
rewrite would give it an object with `embeddings` where `["embedding"]` was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def embed(sentence):
    return genai.embed_content(model="models/gemini-embedding-001", content=sentence)


async def embed_async(sentence):
    return await genai.embed_content_async(model="text-embedding-004", content=sentence)
