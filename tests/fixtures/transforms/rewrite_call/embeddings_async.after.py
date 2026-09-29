"""The async embedding, which is the same rewrite one segment further in.

`aio` is the whole of the difference: the new call is a coroutine on both
sides, so the `await` the author wrote is around the call this rule replaces
and never touched by it.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


async def embed(sentence):
    await client.aio.models.embed_content(model="text-embedding-004", contents=sentence)
