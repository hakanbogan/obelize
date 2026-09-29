"""Nightly digest, written against the SDK without an alias.

The import is spelled out at every call site, which is the one form where there
is no alias to rename and `direct_import_resolved` is the answer.
"""

import os

import google.generativeai

google.generativeai.configure(api_key=os.environ["GEMINI_API_KEY"])


def digest(text):
    model = google.generativeai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(text).text
