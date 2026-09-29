"""A directory that is not a git repository at all, so nothing can be dirty.

RUN_FOLDER.md says `git_dirty` is `false` here and says out loud that this is
also the case in which TM-8 cannot protect anybody. The run writes, and the
report is the only thing standing between the user and a migration they cannot
`git diff`.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
