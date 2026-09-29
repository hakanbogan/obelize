"""Tools on the constructor, where the default flipped between the SDKs.

Automatic function calling is off by default in the old SDK and on by default
in the new one, so a tool declaration moved across unchanged starts calling
the author's functions. The arguments would move cleanly; the behaviour would
not.

The key beside this file is what the rules produce and not what a run
writes: one of them refused, so ADR-010 F-1 leaves the file exactly as it
was.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def lookup(city):
    return city


MODEL = genai.GenerativeModel("gemini-1.5-flash", tools=[lookup])


def answer(prompt):
    return MODEL.generate_content(prompt).text
