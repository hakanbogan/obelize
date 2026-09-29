"""Two `configure()` calls in one module, which withholds all of it."""

import os

import google.generativeai as genai

if os.environ.get("SECONDARY"):
    genai.configure(api_key=os.environ["SECONDARY"])
else:
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "fixture-key"))

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text
