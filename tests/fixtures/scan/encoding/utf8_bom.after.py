"""Support reply drafter."""
import os

from google import genai

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))


def draft(question):
    return client.models.generate_content(model="gemini-1.5-flash", contents=question).text
