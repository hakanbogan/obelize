"""Safety thresholds, read off the enums in the legacy `types` submodule.

The two enum members are attribute findings rather than calls, and the table is
this module's own: it is handed to a caller and never to the SDK.
"""

import os

import google.generativeai as genai
from google.generativeai.types import HarmBlockThreshold, HarmCategory

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

STRICT = {HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH}


def thresholds():
    """What this module recommends. The SDK never sees it."""
    return dict(STRICT)


def draft(question):
    model = genai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(question).text
