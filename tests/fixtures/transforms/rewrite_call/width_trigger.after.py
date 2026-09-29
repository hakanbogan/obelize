"""A configuration too wide for its line, so it breaks and takes the call with it.

The width clause is the one the layout rule's note never had, and this is the
first fixture where both of its consequences are visible in one expression: the
configuration object wraps because its own flat form is too wide for the column
it would start in, and the call around it wraps because one of its arguments is
now multi-line. The author wrote the whole thing on one line, so neither break
is inherited from the source.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def embed(paragraph):
    client.models.embed_content(
        model="models/gemini-embedding-001",
        contents=paragraph,
        config=types.EmbedContentConfig(
            task_type="retrieval_document",
            title="the quarterly report, as filed",
            output_dimensionality=1536,
        ),
    )
