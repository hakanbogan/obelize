"""The repository that is migrated twice, and the file with two hunks.

The second run of the same pack over the same tree writes nothing, reports
`idempotent: true` and has nothing left to verify. The ten unchanged lines in
the middle are deliberate: three lines of context either side of two changes
that far apart do not meet, so this file is the one that proves a patch is
grouped rather than emitted whole.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash")

PROMPT = "Summarise this diff in one sentence."
LIMIT = 4000
RETRIES = 2
SEPARATOR = "\n---\n"
HEADER = "diff"
FOOTER = "end"
TRAILER = "."


def note(diff):
    return MODEL.generate_content(PROMPT + diff).text
