"""Headline generator.

The SDK handle is aliased once at import time so the rest of the module can
stay short. Every real use goes through `g`, never through `genai`.
"""
import os

import google.generativeai as genai

# one short handle for the whole module
g = genai

g.configure(api_key=os.environ["GEMINI_API_KEY"])


def headline(prompt):
    return g.GenerativeModel("gemini-1.5-pro").generate_content(prompt).text


def bullets(prompt, n=5):
    model = g.GenerativeModel("gemini-1.5-flash")
    return model.generate_content("%d bullets:\n%s" % (n, prompt)).text
