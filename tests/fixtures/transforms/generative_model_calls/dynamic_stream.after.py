"""A streaming flag this rule would have to run the program to know.

The two values go to two differently named methods, so a flag that is not a
literal is not a layout question or a default -- it is two rewrites, and the
rule cannot choose between them.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt, live):
    return MODEL.generate_content(prompt, stream=live)
