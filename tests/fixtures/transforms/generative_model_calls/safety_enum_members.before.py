"""The safety table written as enum members rather than as strings.

A member carries across under its own name, because the legacy enums and the
new ones declare the same members -- which is why `HarmBlockThreshold.OFF` is
rewritable here and the string `"off"` is refused next door: the string was
never a key of the legacy lookup and code using one raised `KeyError` before
any migration.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash",
    safety_settings={genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.OFF},
)


def answer(prompt):
    return MODEL.generate_content(prompt).text
