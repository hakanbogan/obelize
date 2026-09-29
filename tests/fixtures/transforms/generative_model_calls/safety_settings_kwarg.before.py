"""A constructor keyword that is rebuilt rather than carried.

A safety table was a mapping of loosely spelled strings and is now a list of
objects built out of two closed enums, so this is the second argument this
rule generates rather than moves. The refusal this file used to grade was the
pack's and not a judgement about the author's code, and the pack has a
destination for it now.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash", safety_settings={"HARM_CATEGORY_HARASSMENT": "BLOCK_ONLY_HIGH"}
)


def answer(prompt):
    return MODEL.generate_content(prompt).text
