"""A configuration name whose mapping is changed after it is assigned.

The literal the rule would copy is not the value the model was built with, so it copies nothing.
Each way a mapping changes is here once: a key stored, and `update`.

The key beside this file is what the rules produce and not what a run writes: one of them
refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

STORED = {"temperature": 0.2}
STORED["top_p"] = 0.8

UPDATED = {"temperature": 0.2}
UPDATED.update(top_p=0.8)

ONE = genai.GenerativeModel("gemini-1.5-flash", generation_config=STORED)
TWO = genai.GenerativeModel("gemini-1.5-flash", generation_config=UPDATED)


def answer(prompt):
    return ONE.generate_content(prompt).text + TWO.generate_content(prompt).text
