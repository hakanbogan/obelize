"""Every spelling of the import in one module, which is the point of the case."""

import types as stdlib_types

import google.generativeai
import google.generativeai as genai
from google import generativeai
from google.generativeai import GenerativeModel
from google.generativeai.types import HarmBlockThreshold, HarmCategory

STRICT = {HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH}


def three_ways(prompt):
    a = google.generativeai.GenerativeModel("gemini-1.5-flash")
    b = generativeai.GenerativeModel("gemini-1.5-flash")
    c = genai.GenerativeModel("gemini-1.5-flash")
    d = GenerativeModel("gemini-1.5-flash")
    assert isinstance(STRICT, stdlib_types.MappingProxyType | dict)
    return [m.generate_content(prompt).text for m in (a, b, c, d)]
