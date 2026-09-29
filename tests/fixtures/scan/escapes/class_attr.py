"""Text classifier.

The model is built once in the class body, so every instance shares it. The
binding lives on the class, not on an instance and not in a function.
"""
import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])


class Classifier:
    """One model per class, not per instance."""

    PROMPT = "Classify the following text. Answer with one label.\n\n%s"
    model = genai.GenerativeModel("gemini-1.5-flash-002")

    def __init__(self, labels):
        self.labels = labels

    def classify(self, text):
        resp = self.model.generate_content(self.PROMPT % text)
        return resp.text.strip()

    def conversation(self):
        return self.model.start_chat(history=[])
