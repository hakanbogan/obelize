"""Write a release note with the Gemini API."""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    """Return one sentence describing ``diff``."""
    return MODEL.generate_content(diff).text
