"""Summarise a text or PDF file with Gemini."""

import os
import sys

import google.generativeai as genai
import PyPDF2

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel("gemini-2.5-flash", generation_config={"temperature": 0.2})


def read(path):
    if path.endswith(".pdf"):
        return "\n".join(page.extract_text() for page in PyPDF2.PdfReader(path).pages)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def summarise(text):
    response = model.generate_content(f"Summarise this in two sentences:\n\n{text}")
    return response.text


if __name__ == "__main__":
    print(summarise(read(sys.argv[1])))
