"""Both names on one `from` line, and both of them consumed.

`GenerativeModel` moved to no module at all and `configure` became an object,
so neither name survives the rewrite. The line that bound them becomes the
module import the two new calls are reached through, which is the answer the
one-rule corpus next door cannot give.
"""

from google.generativeai import GenerativeModel, configure

configure(api_key="AIzaNotARealKey")

MODEL = GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    return MODEL.generate_content(prompt).text
