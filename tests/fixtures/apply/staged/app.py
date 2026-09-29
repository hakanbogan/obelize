"""The same change as `../dirty_worktree/`, in the index rather than the worktree.

`git status --porcelain` reports it in the first of the two status columns
rather than the second, and a reader of that output who looks at one column
sees a clean tree. Staged work is work somebody has not committed, so it is
dirty.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
