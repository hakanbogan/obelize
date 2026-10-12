"""A function's own configuration name, read by two models.

A name that belongs to a function goes with the model that read it. With two readers, writing one
would leave the other reading a name that is gone, so neither is written.

The key beside this file is what the rules produce and not what a run writes: one of them
refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def compare(prompt):
    base = {"temperature": 0.2}
    short = genai.GenerativeModel("gemini-1.5-flash", generation_config=base)
    long = genai.GenerativeModel("gemini-1.5-pro", generation_config=base)
    return short.generate_content(prompt).text + long.generate_content(prompt).text
