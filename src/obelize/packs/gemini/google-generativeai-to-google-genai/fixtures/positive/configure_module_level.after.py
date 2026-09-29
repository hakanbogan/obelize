"""A module-level configure, which is the shape the client rule is written for."""

import os

from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def answer(question):
    return client.models.generate_content(model="gemini-1.5-flash", contents=question).text
