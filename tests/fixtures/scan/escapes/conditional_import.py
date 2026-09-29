"""Compat shim.

The container images are half-migrated: some ship google-generativeai and
some only ship the new package. Both bind the name `genai`, and the module
below is written as if the surface were the same.
"""
import os

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - new images only
    from google import genai


def _configure():
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])


def make_model(name="gemini-1.5-flash"):
    _configure()
    return genai.GenerativeModel(name)


def ask(prompt):
    return make_model().generate_content(prompt).text
