"""A module that already binds the submodule's own name, but not the fallback.

The pack offers two names for the submodule the configuration class lives in.
This file has taken the first, so the second is used -- and the emitted
configuration is spelled against it, because the name a rule writes is the
name the import manager handed back and not the one the pack prefers.
"""

import google.generativeai as genai

types = ("flash", "pro")

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config={"temperature": 0.2})


def answer(prompt):
    return MODEL.generate_content(prompt).text, types
