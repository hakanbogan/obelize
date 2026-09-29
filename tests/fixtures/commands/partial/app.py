"""The file this repository does migrate, beside one no rule may touch.

Same code as `app/app.py`. It is duplicated rather than shared because a
fixture repository is a repository: a case that reached outside its own
directory for half its input would not be one.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
