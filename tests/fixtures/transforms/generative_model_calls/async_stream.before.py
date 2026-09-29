"""The async streaming branch, and the `await` that has to survive it.

ADR-008 wrote this shape with no `await` and called the fix an inserted one.
In the installed 0.8.6 the legacy method is a coroutine function whatever
`stream` is, so the form it describes raised `TypeError` before any migration:
real legacy code has the `await`, the new streaming method is a coroutine
function too, and the `await` is carried over untouched. The edit says so,
because an implementation that derived this from the sync streaming rule would
drop it and the file would fail at runtime rather than at import.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


async def chunks(prompt):
    async for chunk in await MODEL.generate_content_async(prompt, stream=True):
        yield chunk.text
