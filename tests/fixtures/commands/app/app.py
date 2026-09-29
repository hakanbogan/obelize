"""The repository every command in this corpus is pointed at.

Nothing here is withheld: five findings, five of them automatic, two files on
the plan. That is deliberate and it is what makes exit `0` reachable at all --
`docs/CLI.md` narrows `4` to an apply that wrote nothing *or left review items
outstanding*, so a repository with one withheld row can never produce a `0`
from `--apply`, and a corpus built only out of such repositories would grade
that clause vacuously. `partial/` is the other half of the pair.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
