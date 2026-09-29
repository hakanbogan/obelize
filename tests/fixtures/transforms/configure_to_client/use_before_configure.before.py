"""A module-level use of the model above the `configure`.

The legacy model reads its credentials when it sends a request, so a model
used before `configure` in the file is legal. The client it becomes is bound
where the `configure` was, below the line that reads it
(transforms:CODEMOD-10).
"""

import google.generativeai as genai

MODEL = genai.GenerativeModel("gemini-1.5-flash")
WARM = MODEL.count_tokens("hello").total_tokens

genai.configure(api_key="AIzaNotARealKey")


def answer(prompt):
    return MODEL.generate_content(prompt).text
