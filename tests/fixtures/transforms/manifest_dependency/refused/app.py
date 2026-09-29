"""The module that migrates, so every declaration below is owed a new pin."""

import google.generativeai as genai

genai.configure(api_key="")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
