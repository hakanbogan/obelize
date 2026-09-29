"""Vertex AI code path.

`vertexai.generative_models.GenerativeModel` and the `vertexai.preview`
copy of it are a different SDK that happens to expose the same class name
and nearly the same constructor. Neither is google-generativeai.
"""
import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel
from vertexai.preview.generative_models import GenerativeModel as PreviewModel

vertexai.init(project="acme-prod", location="us-central1")

GEN_CONFIG = GenerationConfig(temperature=0.1, max_output_tokens=512)


def summarise(text):
    model = GenerativeModel("gemini-1.5-pro-002", generation_config=GEN_CONFIG)
    return model.generate_content(text).text


def summarise_preview(text):
    model = PreviewModel("gemini-1.5-pro-002")
    out = model.generate_content(text)
    return out.text


def chat(system_instruction=None):
    model = GenerativeModel(
        "gemini-1.5-flash-002",
        system_instruction=system_instruction,
    )
    session = model.start_chat(history=[])
    return session


def chat_preview():
    model = PreviewModel("gemini-1.5-flash-002")
    return model.start_chat(history=[])
