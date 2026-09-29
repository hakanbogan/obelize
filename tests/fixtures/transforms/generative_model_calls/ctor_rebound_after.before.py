"""A model built from a local that is rebound before the model is used.

The model keeps the name it was built with; the rewrite would pass `name` at
the call, after it changed (transforms:CODEMOD-01).
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def answer(prompt):
    name = "gemini-1.5-flash"
    model = genai.GenerativeModel(name)
    name = "gemini-1.5-pro"
    return model.generate_content(prompt).text, name
