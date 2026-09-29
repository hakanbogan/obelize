"""A parameter called `client`, in a function whose model call becomes a client call.

The module's client was named `client` because nothing at module level used
the name. The rewritten call in `answer` then read the parameter instead -- an
HTTP client, whose `.models` raises `AttributeError` (transforms:CODEMOD-02).
A name any scope in the file binds is taken, so the ladder moves on.
"""

from google import genai

genai_client = genai.Client(api_key="AIzaNotARealKey")


def answer(prompt, client=None):
    return genai_client.models.generate_content(model="gemini-1.5-flash", contents=prompt).text
