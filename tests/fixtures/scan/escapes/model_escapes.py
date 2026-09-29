"""Batch jobs.

One model object is built at import time and then shared: cached in a dict,
handed back out of a helper, passed into functions, and read for its name.
"""
import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL = genai.GenerativeModel("gemini-1.5-flash-002")

_REGISTRY = {"default": MODEL}


def get_model(name="default"):
    return _REGISTRY.get(name, MODEL)


def run_with(model, prompt):
    return model.generate_content(prompt).text


def describe():
    return "batch jobs run on %s" % MODEL.model_name


def main(prompts):
    out = []
    for p in prompts:
        out.append(run_with(get_model(), p))
    out.append(run_with(MODEL, "write a one-line summary of the above"))
    return out
