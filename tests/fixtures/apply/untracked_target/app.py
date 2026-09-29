"""A file on the plan that git has never been told about.

It sits beside a committed tree but was never added, so git holds no copy of
it: a rewrite would not show in `git diff`, and `git checkout` could not undo
it. An untracked file on the plan is dirt, and the whole apply is refused.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
