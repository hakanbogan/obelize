"""A safety table held by a module-level name, with the legacy enum members as its keys.

The benchmark's herbal-garden app builds a mapping of category to threshold and hands it to the
constructor by name. The mapping is read where it is assigned and rebuilt as the list of
`SafetySetting` objects the new SDK wants, so the four lines that built it are not call sites and
need no rule. They stay, unread.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")

safety = {
    types.HarmCategory.HARM_CATEGORY_HARASSMENT: types.HarmBlockThreshold.BLOCK_NONE,
    types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: types.HarmBlockThreshold.BLOCK_NONE,
    types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: (
        types.HarmBlockThreshold.BLOCK_NONE
    ),
}


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
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
            ],
        ),
    ).text
