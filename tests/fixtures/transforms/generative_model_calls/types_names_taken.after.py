"""A module that already binds both names the configuration could be imported as.

The configuration class is reached through a submodule, the module has to
bind a name for it, and the pack offers two. When the file has taken both,
there is no name left to introduce and the group is refused with the code the
import manager raises.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

from google import genai

types = {"flash": "gemini-1.5-flash"}
genai_types = {"flash": "gemini-1.5-flash-002"}

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config={"temperature": 0.2})


def answer(prompt):
    return MODEL.generate_content(prompt).text, types, genai_types
