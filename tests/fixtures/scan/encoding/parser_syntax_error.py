"""Nightly report mailer. A hand migration that was never finished."""
import os

import google.generativeai as genai

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", "")
def report(text):
    model = genai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(text).text
