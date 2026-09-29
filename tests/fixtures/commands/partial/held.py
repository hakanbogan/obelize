"""The file a rule refuses, which is what leaves review items outstanding.

`seed` is a key the legacy configuration class never had. The scan grades
every row here `eligible`, a rule then refuses the group, and F-1 withholds
the import rewrite with it. So this repository writes two files and still
has five rows a person has to read, which is the apply `docs/CLI.md` gives
exit `4` -- the outcome nearly every real repository produces and the one the
example application produces too.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config={"seed": 7})


def answer(prompt):
    return MODEL.generate_content(prompt).text
