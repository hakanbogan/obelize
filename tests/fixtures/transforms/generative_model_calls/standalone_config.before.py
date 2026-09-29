"""A configuration object that lives on its own and is handed over by name.

The only place a rewrite can put a configuration is inside the call it
configures, so a name in its place is one this rule cannot follow. Both rows
say so: the constructor because the value it was given is not a shape it can
read, and the object itself because nothing consumed it.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

CONFIG = genai.GenerationConfig(temperature=0.2)

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config=CONFIG)


def answer(prompt):
    return MODEL.generate_content(prompt).text
