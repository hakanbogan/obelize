"""Two entry points, each configuring the SDK for its own account."""
import os

import google.generativeai as genai


def _configure_prod():
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])


def _configure_staging():
    genai.configure(api_key=os.environ["GEMINI_STAGING_API_KEY"])


def build(env="prod"):
    if env == "prod":
        _configure_prod()
    else:
        _configure_staging()
    return genai.GenerativeModel("gemini-1.5-flash-002")


def ask(prompt, env="prod"):
    model = build(env)
    return model.generate_content(prompt).text
