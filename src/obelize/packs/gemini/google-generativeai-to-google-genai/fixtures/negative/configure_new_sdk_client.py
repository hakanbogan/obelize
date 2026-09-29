"""The client this rule produces. Running the rule again must find nothing."""

import os

from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def answer(question):
    return client.models.generate_content(model="gemini-1.5-flash", contents=question).text
