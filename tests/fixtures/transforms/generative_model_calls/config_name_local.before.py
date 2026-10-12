"""A configuration held by a name that belongs to the function that builds the model.

Nothing outside the function can read it, so it goes with the model: once its keys are in the
call there is nothing left for the assignment to do. Both forms the legacy SDK took are here, a
mapping and a `GenerationConfig`, and the second would not survive the import being renamed.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def warm(prompt):
    base = {"temperature": 0.2}
    model = genai.GenerativeModel("gemini-1.5-flash", generation_config=base)
    return model.generate_content(prompt).text


def bold(prompt):
    config = genai.GenerationConfig(temperature=0.9, top_p=0.8)
    model = genai.GenerativeModel("gemini-1.5-flash", generation_config=config)
    return model.generate_content(prompt).text
