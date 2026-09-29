"""The half that does not migrate: the model object leaves the module."""

import google.generativeai as genai

genai.configure(api_key="fixture-key")


def make_model(name):
    """Hand the caller a model, which is what withholds this file."""
    return genai.GenerativeModel(name)


def ask(name, prompt):
    return make_model(name).generate_content(prompt).text
