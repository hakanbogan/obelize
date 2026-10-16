"""The task types the legacy SDK took in other spellings.

The legacy call lowered a string and looked it up, so `"document"` and
`"Retrieval_Query"` both worked. The new configuration sends the string as
written, and the service reads the UPPER_SNAKE name, so the rule writes that.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def embed_document(sentence):
    genai.embed_content(model="models/gemini-embedding-001", content=sentence, task_type="document")


def embed_query(sentence):
    genai.embed_content(
        model="models/gemini-embedding-001",
        content=sentence,
        task_type="Retrieval_Query",
    )
