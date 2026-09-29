"""A comment written about the statement this rule deletes.

`leading_lines` carries blank lines and comments alike, so a deletion that
took the lot would lose the author's prose about code that is going away.
The comment moves onto the statement that now comes first; the blank line
that separated it from the client does not, because that statement has blank
lines of its own.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

# Flash is cheap and fast enough for a summary.
MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text
