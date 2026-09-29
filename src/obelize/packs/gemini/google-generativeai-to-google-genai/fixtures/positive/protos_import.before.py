"""Three surfaces with no v0 target, in the module that also has a real usage."""

import google.generativeai as genai
from google.generativeai import caching, protos

genai.configure(api_key="")

SCHEMA = protos.Schema(type=protos.Type.STRING)


def cached(name):
    return caching.CachedContent.get(name)


def tuned(display_name):
    return genai.create_tuned_model(source_model="models/gemini-1.5-flash", id=display_name)


def answer(question):
    model = genai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(question).text
