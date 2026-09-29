"""The embedding call, its configuration keywords and its result subscript."""

import google.generativeai as genai

genai.configure(api_key="")


def embed(sentence):
    response = genai.embed_content(
        model="models/gemini-embedding-001",
        content=sentence,
        task_type="retrieval_document",
        title="notes",
    )
    return response["embedding"]


async def embed_async(sentence):
    response = await genai.embed_content_async(
        model="models/gemini-embedding-001", content=sentence
    )
    return response["embedding"]
