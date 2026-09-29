"""An embedding whose task type needs a `types` the file binds only for the type checker.

`task_type` moves into `types.EmbedContentConfig(...)`, and the one `types`
here is under `if TYPE_CHECKING:` (transforms:CODEMOD-04).
"""

from typing import TYPE_CHECKING

from google import genai

if TYPE_CHECKING:
    from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def embed(sentence):
    genai.embed_content(
        model="models/gemini-embedding-001",
        content=sentence,
        task_type="retrieval_document",
    )
