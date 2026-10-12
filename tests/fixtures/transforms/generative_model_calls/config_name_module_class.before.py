"""A configuration class held by a module-level name, imported by its own name.

The benchmark's herbal-garden app builds its configuration once, at the top, from the class it
imported out of `google.generativeai.types`, and hands the name to the model. The keys are written
into the call the way a mapping's are. The name stays, since another module may import it, and its
class becomes the new SDK's: the import it came from goes with the legacy SDK.
"""

import google.generativeai as genai
from google.generativeai.types import GenerationConfig

genai.configure(api_key="AIzaNotARealKey")

generation_config = GenerationConfig(
    temperature=0.9,
    top_p=1,
    max_output_tokens=2048,  # the reply is read aloud
)

model = genai.GenerativeModel("gemini-1.5-flash", generation_config=generation_config)


def answer(prompt):
    return model.generate_content(prompt).text
