"""Feature-flagged summariser.

When GEMINI is switched off the module drops the SDK handle on the floor and
falls back to a truncation. The import is still there, so the module still
looks like an SDK user to anything that does not track the reassignment.
"""
import os

import google.generativeai as genai

USE_GEMINI = os.environ.get("USE_GEMINI") == "1"

if not USE_GEMINI:
    genai = None
else:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash-002") if USE_GEMINI else None


def summarise(text):
    if MODEL is None:
        return text[:280]
    return MODEL.generate_content(text).text
