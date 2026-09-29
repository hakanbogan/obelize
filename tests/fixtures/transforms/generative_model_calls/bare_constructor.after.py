"""C-21: a constructor with no model name at all.

The legacy signature defaults the name and the new call requires it, so the
pack has to carry a default -- and the model it defaults to is itself retired,
which is why this is reported rather than substituted silently.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel()


def answer(prompt):
    return MODEL.generate_content(prompt).text
