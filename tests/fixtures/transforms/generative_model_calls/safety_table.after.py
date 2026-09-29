"""The safety table, at every rung the legacy lookup had.

The legacy SDK lower-cased whatever it was handed and looked it up in a closed
dictionary, so `HARM_CATEGORY_HARASSMENT`, `Hate`, `sex` and `danger` are four
spellings of four categories and `BLOCK_NONE`, `low`, `MED` and `high` are four
spellings of four thresholds. Every one of the eight is a row of the pack's
tables; a ninth is refused next door.
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
                    threshold=types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
                ),
            ],
        ),
    ).text
