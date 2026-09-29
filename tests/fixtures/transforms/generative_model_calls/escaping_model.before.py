"""A model handed to something else, which the scan withholds before any rule.

Nothing here is eligible, so this rule is never asked about any of it and the
file comes back exactly as it was. The case is in the corpus because the rule
still walks the bindings, and one that the scan refused must not become a
group.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")
HANDLES = [MODEL]


def answer(prompt):
    return MODEL.generate_content(prompt).text
