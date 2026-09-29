"""Support reply drafter."""
import os

import google.generativeai as genai

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))


def draft(question):
    model = genai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(question).text
