"""The same class name from a different SDK, imported from both live origins."""

import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel
from vertexai.preview.generative_models import GenerativeModel as PreviewModel

vertexai.init(project="example", location="us-central1")


def answer(question):
    model = GenerativeModel("gemini-1.5-flash")
    return model.generate_content(
        question, generation_config=GenerationConfig(temperature=0.2)
    ).text


def preview(question):
    return PreviewModel("gemini-1.5-flash").generate_content(question).text
