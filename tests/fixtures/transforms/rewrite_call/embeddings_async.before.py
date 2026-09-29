"""The async embedding, which is the same rewrite one segment further in.

`aio` is the whole of the difference: the new call is a coroutine on both
sides, so the `await` the author wrote is around the call this rule replaces
and never touched by it.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


async def embed(sentence):
    await genai.embed_content_async(model="text-embedding-004", content=sentence)
