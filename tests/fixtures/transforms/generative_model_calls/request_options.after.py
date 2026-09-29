"""A call keyword with no counterpart on the new method.

The new methods are keyword-only and take a fixed set, so a keyword outside it
is not something to move: the per-request options it carried are configured a
different way entirely.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt, request_options={"timeout": 5}).text
