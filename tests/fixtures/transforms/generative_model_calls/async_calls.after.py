"""The async methods, where the `await` the author wrote is left alone.

Both sides are coroutine functions, so the rewrite is the method name and the
service and nothing else -- the `await` is not this rule's to move, and the
async model calls hang off a different service of the same client.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


async def answer(prompt):
    response = await client.aio.models.generate_content(model="gemini-1.5-flash", contents=prompt)
    return response.text


async def size(prompt):
    counted = await client.aio.models.count_tokens(model="gemini-1.5-flash", contents=prompt)
    return counted.total_tokens
