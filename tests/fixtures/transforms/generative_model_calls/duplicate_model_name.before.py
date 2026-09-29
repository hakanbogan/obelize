"""The model named twice, once by position and once by keyword.

The legacy call raises `TypeError` for this, so the file is already broken --
which is exactly why the rule refuses rather than picking one of the two. A
rewrite that quietly chose would turn code that fails loudly into code that
runs against a model nobody asked for.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", model_name="gemini-1.5-pro")


def answer(prompt):
    return MODEL.generate_content(prompt).text
