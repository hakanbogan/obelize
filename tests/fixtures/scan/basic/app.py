"""Summarise release notes with the Gemini API."""

import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])  # keep this comment

MODEL = genai.GenerativeModel("gemini-1.5-flash", generation_config=genai.GenerationConfig(temperature=0.2, max_output_tokens=512))


def summarize(prompt):
    """Return a two-sentence summary of ``prompt``."""
    response = MODEL.generate_content(
        f"Summarize the following in exactly two sentences:\n\n{prompt}",
    )
    return response.text


def count_tokens(prompt):
    return MODEL.count_tokens(prompt).total_tokens
