"""The shape the client rule is written for: one module-level `configure`.

Nothing else here is legacy, so the two implemented rules migrate the whole
file and the key beside it is what `obelize fix --apply` writes.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
