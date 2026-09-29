"""The other shape the legacy SDK took: a list of one-row mappings.

Both forms mean the same thing and both become the same list of objects, so
the two keys of a row are pack data rather than something the rule knows --
they are spelled the way the new class spells its arguments here, and that is
a coincidence of this pair of SDKs.
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
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
                ),
            ],
        ),
    ).text
