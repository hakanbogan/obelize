"""The middle rung of the naming ladder: `client` is taken, `genai_client` is not.

The module binds `client` for something of its own, so the rewrite takes the
pack's `client_name_fallback` rather than shadowing a name the author chose.
"""

import os

from google import genai

client = os.environ.get("HTTP_CLIENT", "requests")

genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
