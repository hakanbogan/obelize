"""A committed tree with untracked files beside it, which is not a dirty tree.

`.obelize/latest` is the file obelize writes itself, and counting it would
make every run after the first one refuse to write anything. Neither
untracked file is on the plan, and `../untracked_target/` is one that is.
`../staged/` is the same file after a `git add`, which is dirty.
"""

import os

from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def note(diff):
    return client.models.generate_content(model="gemini-1.5-flash", contents=diff).text
