"""One-shot prompt runner."""
import os

from google import genai

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
print(client.models.generate_content(model="gemini-1.5-flash", contents="ping").text)