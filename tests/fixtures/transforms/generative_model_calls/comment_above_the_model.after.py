"""A comment written about the statement this rule deletes.

`leading_lines` carries blank lines and comments alike, so a deletion that
took the lot would lose the author's prose about code that is going away.
The comment moves onto the statement that now comes first; the blank line
that separated it from the client does not, because that statement has blank
lines of its own.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


# Flash is cheap and fast enough for a summary.
def answer(prompt):
    return client.models.generate_content(model="gemini-1.5-flash", contents=prompt).text
