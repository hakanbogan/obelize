"""Listing and getting a model, the two calls the migration guide omits."""

import google.generativeai as genai

genai.configure(api_key="")


def names():
    return [entry.name for entry in genai.list_models()]


def details():
    return genai.get_model("models/gemini-1.5-flash")
