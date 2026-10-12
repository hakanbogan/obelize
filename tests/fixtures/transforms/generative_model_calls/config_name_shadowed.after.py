"""A configuration name that is a parameter where the model is built.

The module has a name of that spelling with a mapping of legal keys. The function takes its own,
so the call reads whatever the caller passed, and the module's mapping is the wrong one to copy.

The key beside this file is what the rules produce and not what a run writes: one of them
refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

CONFIG = {"temperature": 0.2}


def answer(prompt, CONFIG):
    model = genai.GenerativeModel("gemini-1.5-flash", generation_config=CONFIG)
    return model.generate_content(prompt).text
