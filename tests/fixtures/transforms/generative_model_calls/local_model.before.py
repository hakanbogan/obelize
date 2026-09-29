"""A model built and read inside one function, with the client above it.

The binding is a local rather than a module constant, which is a different
row of the resolution table and the same rewrite: the constructor goes and
the name it bound stops existing.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def answer(prompt):
    model = genai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(prompt).text
