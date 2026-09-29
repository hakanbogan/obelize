"""C-23: a configuration key the legacy class never had.

`seed` exists on the new configuration object, so carrying it across looks
free. It reached the legacy SDK only through the unvalidated mapping form and
the server rejected it, so the code was already broken and a rewrite that
quietly made it work would be inventing behaviour.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config={"seed": 7})


def answer(prompt):
    return MODEL.generate_content(prompt).text
