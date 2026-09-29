"""The safety table written as enum members rather than as strings.

A member carries across under its own name, because the legacy enums and the
new ones declare the same members -- which is why `HarmBlockThreshold.OFF` is
rewritable here and the string `"off"` is refused next door: the string was
never a key of the legacy lookup and code using one raised `KeyError` before
any migration.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def answer(prompt):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
            ],
        ),
    ).text
