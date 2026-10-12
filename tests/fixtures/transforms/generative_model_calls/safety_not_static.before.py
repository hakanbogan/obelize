"""A safety table held by a name, changed after the name is assigned.

The rule resolves every category and every threshold against a closed table before it emits one,
because the new enums fabricate an unknown member with only a warning. A table that a later line
adds to is not the one written where the name is assigned, and what it holds at the call is a
value the rule would have to run the program to know.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

POLICY = {"harassment": "block_none"}
POLICY["hate"] = "block_none"

MODEL = genai.GenerativeModel("gemini-1.5-flash", safety_settings=POLICY)


def answer(prompt):
    return MODEL.generate_content(prompt).text
