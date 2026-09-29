"""A repository the *scan* already refused, and no manifest at all.

The module alias is rebound, so every row in this file is withheld before a
rule is asked about any of them: the rules claim the rows and record nothing,
the driver adds no code of its own, and the `caused_by` a reader sees is the
one the scan wrote.

There is no manifest here on purpose. F-2 grades declarations and this
repository has none, so the manifest pass has nothing to run over and the run
writes no file at all.
"""

import google.generativeai as genai

g = genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")
