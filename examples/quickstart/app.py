"""Summarise a text file with Gemini."""

import os
import sys

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel("gemini-2.5-flash", generation_config={"temperature": 0.2})


def summarise(text):
    response = model.generate_content(f"Summarise this in two sentences:\n\n{text}")
    return response.text


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as handle:
        print(summarise(handle.read()))
