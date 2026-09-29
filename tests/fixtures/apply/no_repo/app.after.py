"""A directory that is not a git repository at all, so nothing can be dirty.

RUN_FOLDER.md says `git_dirty` is `false` here and says out loud that this is
also the case in which TM-8 cannot protect anybody. The run writes, and the
report is the only thing standing between the user and a migration they cannot
`git diff`.
"""

import os

from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def note(diff):
    return client.models.generate_content(model="gemini-1.5-flash", contents=diff).text
