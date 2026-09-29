"""The file a rule refuses, and therefore the file with findings and no edits.

`seed` is a key the legacy configuration class never had. The scan grades every
row here `eligible`, a rule then refuses the group, and F-1 withholds the
import rewrite with it -- so this file produces four findings, four refused
edits, and no line in the patch.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config={"seed": 7})


def answer(prompt):
    return MODEL.generate_content(prompt).text
