"""The repository whose apply is refused, and still leaves a plan behind.

The tree is committed and then edited, so `fsutil.apply` refuses the whole run
over the tree rather than over the files on the plan. Nothing is written, and
the run folder is written anyway: what it would have done is the useful half
of a refusal.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
