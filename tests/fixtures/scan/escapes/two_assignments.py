"""Summaries with a deployment-specific fallback.

The name is rebound when the primary model is not the one to use, so no single
constructor governs the use below it. Two assignments reach one name and only
one of them builds a legacy object: counting the constructors would call this
group closed-world, and counting the assignments is what does not.
"""
import os

import google.generativeai as genai
from myapp import registry

genai.configure(api_key=os.environ["GEMINI_API_KEY"])


def summarise(text, fallback=False):
    model = genai.GenerativeModel("gemini-1.5-flash-002")
    if fallback:
        model = registry.default_model()
    return model.generate_content(text).text
