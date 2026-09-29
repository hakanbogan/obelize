"""Calls inside handlers for the exceptions the legacy SDK raised.

google-generativeai raised `google.api_core.exceptions`, and google-genai
raises `google.genai.errors.APIError` with a status code on it and no class
per status. A handler naming the old class still compiles and never runs, so
the retry it was written for is gone. Both spellings of the class are here.
"""

import time

import google.api_core.exceptions
import google.generativeai as genai
from google.api_core import exceptions

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def answer(prompt):
    try:
        return MODEL.generate_content(prompt).text
    except exceptions.ResourceExhausted:
        time.sleep(1)
        return MODEL.generate_content(prompt).text


def summary(text):
    try:
        return MODEL.generate_content(text).text
    except google.api_core.exceptions.DeadlineExceeded:
        return ""
