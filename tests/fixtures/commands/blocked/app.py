"""A module that would migrate whole, in a project that cannot take the new SDK.

`pyproject.toml` declares `requires-python = ">=3.8"`, and google-genai needs
3.10, so the scan reports the repository `blocked: runtime_unsupported`. Until
T61 `obelize fix --apply` rewrote this file anyway (scan:SCAN-07).
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def note(diff):
    return MODEL.generate_content(diff).text
