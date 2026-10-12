"""A configuration object that lives on its own, read by nothing in the file.

The only place a rewrite can put a configuration is inside the call it
configures, so an object no call reads is one this rule cannot place. Its
row says so, while the model beside it, which was never handed the object,
is rewritten.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

CONFIG = genai.GenerationConfig(temperature=0.2)

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text
