"""Worker module.

`configure()` is called once in app/bootstrap.py, which this module never
imports. Nothing in this file tells you where the credentials come from.
"""
import google.generativeai as genai

MODEL_NAME = "gemini-1.5-flash-002"


def classify(text):
    model = genai.GenerativeModel(MODEL_NAME)
    return model.generate_content(text).text
