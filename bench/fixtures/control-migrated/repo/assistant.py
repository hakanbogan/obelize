"""Already on the new SDK: nothing here may be reported or rewritten."""

import os

from google import genai

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", "fixture-key"))


def summarize(prompt):
    response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
    return response.text
