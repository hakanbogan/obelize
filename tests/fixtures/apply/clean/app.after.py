"""The repository that reaches a disk whole.

Nothing refuses, the tree is committed and clean, and both files this run
produces are replaced in place. What is graded here that no corpus before it
could grade is the *disk*: every corpus up to T16 compared bytes a driver
returned, and this one compares bytes that survived a temporary file, an
`fsync`, a `chmod` and a rename.
"""

import os

from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def note(diff):
    return client.models.generate_content(model="gemini-1.5-flash", contents=diff).text
