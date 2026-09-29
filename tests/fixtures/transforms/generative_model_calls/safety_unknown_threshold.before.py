"""A threshold spelled the way the enum member is, as a string.

`HarmBlockThreshold.OFF` is a member of both enums and is rewritten next door.
The string `"off"` is not a key of the legacy table and never was, so this
file is the same distinction from the other side.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", safety_settings={"harassment": "off"})


def answer(prompt):
    return MODEL.generate_content(prompt).text
