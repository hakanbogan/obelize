"""A module alias the author chose, which survives the rewrite unchanged.

The `configure` call below belongs to a rule that does not exist yet, so
`obelize fix --apply` writes nothing here: the key beside this file is this one
rule's output and its answer row is graded `complete: false`.
"""

import os

from google import genai as gai
from google.genai import types

gai.configure(api_key=os.environ["GEMINI_API_KEY"])

STRICT = {types.HarmCategory.HARM_CATEGORY_HATE_SPEECH}
