"""A system instruction written as a mapping with a bare string part.

The legacy constructor turned it into a message; the new configuration
validates it and raises a pydantic `ValidationError` for a string where a
`{"text": ...}` part belongs. A mapping already in that shape is carried as
written, and any other is refused.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash", system_instruction={"role": "user", "parts": ["Be brief."]}
)


def answer(prompt):
    return MODEL.generate_content(prompt).text
