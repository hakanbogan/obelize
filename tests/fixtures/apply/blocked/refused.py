"""The file a rule refuses, which must be byte-identical when the run is over.

`seed` is a key the legacy configuration class never had, so the mapping form
carried it to a server that rejected it. The refusal happens after the scan
has graded every row here `eligible`, and F-1 then withholds the import
rewrite too -- so the whole file is left alone while `good.py` beside it is
replaced.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config={"seed": 7})


def answer(prompt):
    return MODEL.generate_content(prompt).text
