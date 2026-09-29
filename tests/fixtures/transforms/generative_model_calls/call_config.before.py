"""A configuration on the constructor and another on the call.

The legacy SDK merged the two and let the call win key by key, so the call's
temperature replaces the constructor's in the constructor's position and the
key only the constructor has is kept.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash", generation_config={"temperature": 0.2, "top_p": 0.9}
)


def answer(prompt):
    return MODEL.generate_content(prompt, generation_config={"temperature": 0.9}).text
