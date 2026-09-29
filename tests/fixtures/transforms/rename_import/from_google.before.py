"""C-27's spelling: the package imported the way the new SDK's own idiom reads.

The `configure` call below belongs to a rule that does not exist yet, so
`obelize fix --apply` writes nothing here: the key beside this file is this one
rule's output and its answer row is graded `complete: false`.
"""

import os

from google import generativeai

generativeai.configure(api_key=os.environ["GEMINI_API_KEY"])


def summarise(text):
    model = generativeai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(text).text
