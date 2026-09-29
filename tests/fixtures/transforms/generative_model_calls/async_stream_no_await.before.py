"""An async stream iterated with no `await`, which never ran.

In google-generativeai 0.8.6 `generate_content_async` is a coroutine function
whatever `stream` is, so this file raises `TypeError: 'coroutine' object is
not async iterable` before any migration. There is nothing to preserve and
nothing to infer, so the group is refused rather than guessed at.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


async def chunks(prompt):
    async for chunk in MODEL.generate_content_async(prompt, stream=True):
        yield chunk.text
