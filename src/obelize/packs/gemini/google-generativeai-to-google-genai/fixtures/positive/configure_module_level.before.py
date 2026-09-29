"""A module-level configure, which is the shape the client rule is written for."""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])


def answer(question):
    model = genai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(question).text
