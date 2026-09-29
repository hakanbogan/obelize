"""The aliased module import, and a safety table reached through the alias.

The `configure` call below belongs to a rule that does not exist yet, so
`obelize fix --apply` writes nothing here: the key beside this file is this one
rule's output and its answer row is graded `complete: false`.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

STRICT = {genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH}
