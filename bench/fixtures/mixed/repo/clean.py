"""The half of this fixture that migrates."""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "fixture-key"))

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def summarize(prompt):
    """Return the model's answer for ``prompt``."""
    return MODEL.generate_content(prompt).text
