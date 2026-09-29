"""A constructor keyword that is rebuilt rather than carried.

A safety table was a mapping of loosely spelled strings and is now a list of
objects built out of two closed enums, so this is the second argument this
rule generates rather than moves. The refusal this file used to grade was the
pack's and not a judgement about the author's code, and the pack has a
destination for it now.
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
                    threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
                ),
            ],
        ),
    ).text
