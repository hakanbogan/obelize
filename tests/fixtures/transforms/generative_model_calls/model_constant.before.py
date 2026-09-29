"""The easy migration reduced to what this rule owns.

A module-level model constant with an inline configuration, read by one call
that generates content and one that counts tokens. The token count cannot
carry the configuration, so that edit says so and the group stays automatic.
"""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel(
    "gemini-1.5-flash",
    generation_config=genai.GenerationConfig(temperature=0.2, max_output_tokens=512),
)


def summarize(prompt):
    return MODEL.generate_content(prompt).text


def size(prompt):
    return MODEL.count_tokens(prompt).total_tokens
