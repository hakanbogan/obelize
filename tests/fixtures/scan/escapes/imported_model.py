"""A model another module imports by name.

Nothing in this file lets the model go anywhere: one constructor, one use,
no escape. `imports_the_model.py` imports it, and a closed world of one file
would delete the constructor and leave that import failing when it runs.
"""
import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text
