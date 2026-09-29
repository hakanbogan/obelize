"""A worker whose credentials are configured somewhere this module cannot see."""

import google.generativeai as genai

MODEL_NAME = "gemini-1.5-flash-002"


def classify(text):
    model = genai.GenerativeModel(MODEL_NAME)
    return model.generate_content(text).text
