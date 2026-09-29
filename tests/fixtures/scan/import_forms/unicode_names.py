"""A model and a function named outside ASCII, which Python allows.

A name is an identifier when Python says so, and `modèle` and `üret` are. Until
T62 a binding named like this failed a model's ASCII check and took the whole
scan down with it (scan:SCAN-04).
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

modèle = genai.GenerativeModel("gemini-1.5-flash")


def üret(istem):
    return modèle.generate_content(istem).text
