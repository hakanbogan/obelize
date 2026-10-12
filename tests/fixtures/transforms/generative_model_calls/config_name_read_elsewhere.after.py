"""A configuration name that something besides the model reads.

The copy in the call would leave the other reader on a value that no longer has a model behind
it, and a function's own name could not be dropped. Only a name whose every read is the
configuration of a call the rule rewrites is followed.

The key beside this file is what the rules produce and not what a run writes: one of them
refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

CONFIG = {"temperature": 0.2}

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config=CONFIG)


def answer(prompt):
    print("asking with", CONFIG)
    return MODEL.generate_content(prompt).text
