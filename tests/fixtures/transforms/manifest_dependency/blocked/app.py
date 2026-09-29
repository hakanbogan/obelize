"""The module that migrates, which is what makes the new pin owed at all."""

import google.generativeai as genai

genai.configure(api_key="")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
