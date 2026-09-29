"""The other shape the legacy SDK took: a list of one-row mappings.

Both forms mean the same thing and both become the same list of objects, so
the two keys of a row are pack data rather than something the rule knows --
they are spelled the way the new class spells its arguments here, and that is
a coincidence of this pair of SDKs.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash",
    safety_settings=[
        {"category": "harassment", "threshold": "block_none"},
        {"category": "hate_speech", "threshold": "block_only_high"},
    ],
)


def answer(prompt):
    return MODEL.generate_content(prompt).text
