"""A file every other rule migrates whole, so this one has nothing to say.

The negative case, and it has to be a file the scan *reads*: a module with no
prefilter token is skipped unparsed and proves only that the prefilter works.
"""

import google.generativeai as genai

genai.configure(api_key="")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
