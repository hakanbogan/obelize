"""A configuration name with two assignments, and no way to say which the call reads.

Both are mappings of legal keys, so each would be fine alone. Which one the model gets depends on
which line ran last, and the rule reads source, not a run.

The key beside this file is what the rules produce and not what a run writes: one of them
refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

import os  # noqa: E402

CONFIG = {"temperature": 0.2}
if os.environ.get("BOLD"):
    CONFIG = {"temperature": 0.9}

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config=CONFIG)


def answer(prompt):
    return MODEL.generate_content(prompt).text
