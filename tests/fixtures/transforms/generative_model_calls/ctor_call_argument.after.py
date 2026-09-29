"""A model whose name is read from a file when it is built.

The rewrite would paste `open(...).read().strip()` into both calls: the file
read on every request instead of once, and a different model the moment the
file changes (transforms:CODEMOD-01).
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(open("model.txt").read().strip())


def answer(prompt):
    return MODEL.generate_content(prompt).text


def size(prompt):
    return MODEL.count_tokens(prompt).total_tokens
