"""The module that blocks the removal, so every edit here is an insertion."""

import google.generativeai as genai

MODEL_NAME = "gemini-1.5-flash-002"


def classify(text):
    model = genai.GenerativeModel(MODEL_NAME)
    return model.generate_content(text).text
