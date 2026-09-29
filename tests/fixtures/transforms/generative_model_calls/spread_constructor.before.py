"""A constructor whose keywords are not written down anywhere.

Every legacy constructor parameter has a destination in the pack or it has
none, and a mapping spread across the call is neither: the rule would have to
run the program to know which keywords it holds. It is legal legacy code,
which is what separates it from the keyword that is simply wrong.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

OPTIONS = {"system_instruction": "Be terse."}

MODEL = genai.GenerativeModel("gemini-1.5-flash", **OPTIONS)


def answer(prompt):
    return MODEL.generate_content(prompt).text
