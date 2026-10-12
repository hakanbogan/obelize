"""A configuration class held by a module-level name, imported by its own name.

The benchmark's herbal-garden app builds its configuration once, at the top, from the class it
imported out of `google.generativeai.types`, and hands the name to the model. The keys are written
into the call the way a mapping's are. The name stays, since another module may import it, and its
class becomes the new SDK's: the import it came from goes with the legacy SDK.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")

generation_config = types.GenerateContentConfig(
    temperature=0.9,
    top_p=1,
    max_output_tokens=2048,  # the reply is read aloud
)


def answer(prompt):
    return client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.9,
            top_p=1,
            max_output_tokens=2048,
        ),
    ).text
