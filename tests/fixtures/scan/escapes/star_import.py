"""Notebook-derived helper.

Written by copying a Colab cell; the star import is load-bearing because
`configure` and `GenerativeModel` are used unqualified below.
"""
import os

from google.generativeai import *

configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = GenerativeModel("gemini-1.5-flash")


def ask(prompt):
    if len(prompt) > 4000:
        prompt = prompt[:4000]
    return MODEL.generate_content(prompt).text
