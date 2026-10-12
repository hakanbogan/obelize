"""A safety table held by a module-level name, with the legacy enum members as its keys.

The benchmark's herbal-garden app builds a mapping of category to threshold and hands it to the
constructor by name. The mapping is read where it is assigned and rebuilt as the list of
`SafetySetting` objects the new SDK wants, so the four lines that built it are not call sites and
need no rule. They stay, unread.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

safety = {
    genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
    genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: genai.types.HarmBlockThreshold.BLOCK_NONE,
    genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: (
        genai.types.HarmBlockThreshold.BLOCK_NONE
    ),
}

model = genai.GenerativeModel("gemini-1.5-flash", safety_settings=safety)


def answer(prompt):
    return model.generate_content(prompt).text
