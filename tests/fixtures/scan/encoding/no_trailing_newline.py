"""One-shot prompt runner."""
import os

import google.generativeai as genai

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

MODEL = genai.GenerativeModel("gemini-1.5-flash")
print(MODEL.generate_content("ping").text)