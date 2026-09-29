# This is the local `genai` package in this repo, not google.generativeai.
import genai

configure = genai.configure

model = genai.GenerativeModel("x")


def run(prompt):
    return model.generate_content(prompt).text
