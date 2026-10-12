"""A generation config held by a module-level name, read by a model built in a function.

A chat bot in the benchmark passes its four keys by name. The name has one assignment, a mapping
of four legal keys, and the model is its only reader, so the keys can be written into the call
the way an inline mapping is. The name stays where it is: another module may import it, and
nothing about it needs to change.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

GENERATION_CONFIG = {
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 1024,
}


def reply(text):
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash", generation_config=GENERATION_CONFIG
    )
    chat = model.start_chat()
    return chat.send_message(text).text
