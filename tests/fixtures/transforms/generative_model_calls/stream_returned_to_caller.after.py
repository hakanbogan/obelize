"""A stream handed back to whoever called for it.

Nothing in this file reads it, so nothing here says whether the caller walks
it or reads `text` off it -- and only the first survives the rewrite.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def chunks(prompt):
    return MODEL.generate_content(prompt, stream=True)
