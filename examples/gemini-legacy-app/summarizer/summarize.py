"""Turn a blob of text into a short summary."""

import google.generativeai as genai

from . import config

PROMPT = (
    "Summarise the text below in at most {n} sentences. "
    "Keep proper nouns. Do not add anything that is not in the text.\n\n"
    "---\n{body}\n---"
)

# Low temperature: we want the same summary twice for the same input.
GENERATION_CONFIG = {
    "temperature": 0.2,
    "top_p": 0.95,
    "max_output_tokens": 512,
}

SAFETY_SETTINGS = {
    "HARM_CATEGORY_HARASSMENT": "BLOCK_ONLY_HIGH",
    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_MEDIUM_AND_ABOVE",
}


def _model():
    return genai.GenerativeModel(
        config.MODEL_NAME,
        generation_config=GENERATION_CONFIG,
        safety_settings=SAFETY_SETTINGS,
        system_instruction="You are a terse technical editor.",
    )


def summarize_text(body, sentences=3):
    """Summarise `body`. Returns the summary as a string."""
    if not body.strip():
        raise ValueError("nothing to summarise")
    response = _model().generate_content(PROMPT.format(n=sentences, body=body))
    return response.text.strip()


def summarize_file(path, sentences=3):
    with open(path, encoding="utf-8") as fh:
        return summarize_text(fh.read(), sentences=sentences)
