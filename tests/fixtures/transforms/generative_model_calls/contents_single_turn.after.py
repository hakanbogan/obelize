"""One turn as the model's input, which the legacy SDK took and the new one does not.

`generate_content` took a single `{"role": ..., "parts": [...]}` mapping. The
new call wants a list of them, or parts, and validates a string part out.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def ask(question):
    return MODEL.generate_content({"role": "user", "parts": [question]}).text
