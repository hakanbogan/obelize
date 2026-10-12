"""A configuration object held by a module-level name, spelled through the module.

`genai.GenerationConfig` is a symbol this rule claims itself, where the spelling through the
`types` submodule is the import rule's. The object stays under its name, as the same keys in the
new SDK's class, and the model that read it gets them in its call.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

CONFIG = genai.GenerationConfig(temperature=0.2)

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config=CONFIG)


def answer(prompt):
    return MODEL.generate_content(prompt).text
