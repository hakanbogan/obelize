"""The file a *rule* refuses, which no scan of this repository can know.

`seed` is a key the legacy configuration class never had, so the mapping form
carried it to a server that rejected it and a rewrite that made it work would
be inventing behaviour. Every row in this file is `eligible` after the scan;
the refusal happens when `generative_model_calls` reads the mapping, and
ADR-010 F-1 then leaves the file exactly as it was.

That is what the manifest beside this file is a measurement of: a run that
graded the repository once, at scan time, would have replaced the legacy pin.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config={"seed": 7})


def answer(prompt):
    return MODEL.generate_content(prompt).text
