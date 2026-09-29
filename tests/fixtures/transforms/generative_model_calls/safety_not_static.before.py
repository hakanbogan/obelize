"""A safety table this rule cannot read, because it is a name.

The rule resolves every category and every threshold against a closed table
before it emits one, because the new enums fabricate an unknown member with
only a warning. A name is a value it would have to run the program to know.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

POLICY = {"harassment": "block_none"}

MODEL = genai.GenerativeModel("gemini-1.5-flash", safety_settings=POLICY)


def answer(prompt):
    return MODEL.generate_content(prompt).text
