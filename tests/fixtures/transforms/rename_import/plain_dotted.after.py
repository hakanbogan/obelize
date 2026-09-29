"""The un-aliased form, where the rewrite is the one that introduces a name.

The `configure` call below belongs to a rule that does not exist yet, so
`obelize fix --apply` writes nothing here: the key beside this file is this one
rule's output and its answer row is graded `complete: false`.
"""

import os

from google import genai

google.generativeai.configure(api_key=os.environ["GEMINI_API_KEY"])


def digest(text):
    model = google.generativeai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(text).text
