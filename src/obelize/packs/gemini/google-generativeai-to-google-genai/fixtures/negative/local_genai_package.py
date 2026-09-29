"""A repository's own package called `genai`. The name is not the SDK."""

import genai
from genai.models import GenerativeModel


def answer(question):
    genai.configure(api_key="local")
    return GenerativeModel("in-house").generate_content(question).text
