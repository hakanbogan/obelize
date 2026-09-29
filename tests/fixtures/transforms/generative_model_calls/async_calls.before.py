"""The async methods, where the `await` the author wrote is left alone.

Both sides are coroutine functions, so the rewrite is the method name and the
service and nothing else -- the `await` is not this rule's to move, and the
async model calls hang off a different service of the same client.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


async def answer(prompt):
    response = await MODEL.generate_content_async(prompt)
    return response.text


async def size(prompt):
    counted = await MODEL.count_tokens_async(prompt)
    return counted.total_tokens
