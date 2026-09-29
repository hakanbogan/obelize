"""The same repository, with a `.obelize.yml` that names a command.

Nothing about the code differs from `app/app.py`. What differs is that the
verification command is the **repository's** and not the user's, which is the
one input ADR-007's ladder reads.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
