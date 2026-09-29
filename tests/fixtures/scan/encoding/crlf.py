"""Nightly digest job."""
import os

import google.generativeai as genai

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))


def digest(text):
    model = genai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(text).text
