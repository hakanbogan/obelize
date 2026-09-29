"""Optional dependency, imported inside the function that needs it.

The SDK is imported where it is used, so importing this module does not require
it to be installed. Every use in the function resolves and the binding is
closed-world; the one thing v0 will not rewrite is the import statement itself,
which is not a module-level statement, so F-1 leaves the rest of the file alone.
"""
import os


def build():
    """Configure the SDK and hand back a model, on first use."""
    import google.generativeai as genai

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    return genai.GenerativeModel("gemini-1.5-flash-002")


def render(rows):
    """A local import of something else entirely, which must not be reported."""
    import json

    return json.dumps(rows, indent=2)
