"""The client rule refused, so there is nothing to spell these calls against.

The defect is the `transport=` keyword and it is reported once, on the line
that carries it. This rule refuses with the same code rather than inventing a
second name for one defect, which is what `caused_by` exists to avoid.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey", transport="rest")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text
