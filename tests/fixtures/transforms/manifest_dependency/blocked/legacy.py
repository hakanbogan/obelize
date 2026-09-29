"""The module that cannot migrate: its credentials are configured elsewhere.

It still imports the legacy distribution after the run, so removing the legacy
pin would turn the next install into an ImportError for this file alone --
which is the whole of ADR-010 F-2's second half.
"""

import google.generativeai as genai

MODEL_NAME = "gemini-1.5-flash-002"


def classify(text):
    model = genai.GenerativeModel(MODEL_NAME)
    return model.generate_content(text).text
