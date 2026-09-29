"""Process-wide SDK setup.

Imported for its side effect: this is the one module in the package that calls
`genai.configure`, and every other module relies on it having run.
"""

import os

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Gemini 1.5 Flash is cheap and fast enough for summaries.
MODEL_NAME = os.environ.get("SUMMARIZER_MODEL", "gemini-1.5-flash")

# Empty string rather than None so importing the package never reaches the
# credentials machinery; the API rejects the empty key on the first real call,
# which is what we want in tests.
API_KEY = os.environ.get("GEMINI_API_KEY", "")

genai.configure(api_key=API_KEY)
